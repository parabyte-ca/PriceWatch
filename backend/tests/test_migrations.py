"""Upgrading a populated database must never lose rows (SQLite batch rebuilds plus FK cascades)."""

import sqlite3

from alembic import command
from pricewatch.migrate import alembic_config


def test_upgrade_from_0001_keeps_child_rows(tmp_path):
    db = tmp_path / "old.db"
    url = f"sqlite:///{db}"
    command.upgrade(alembic_config(url), "0001")
    con = sqlite3.connect(db)
    cols = ("name,condition,priority,hot,active,exclude_refurbished,exclude_open_box,exclude_used,"
            "exclude_marketplace,exclude_bundles,exclude_variants,created_at,updated_at")
    con.execute(f"insert into items({cols}) values ('Old','new',3,0,1,1,1,1,1,1,1,datetime('now'),datetime('now'))")
    con.execute("insert into retailers(domain,name,adapter,fetch_mode,respect_robots,price_match,backoff_seconds,created_at)"
                " values('a.ca','A','generic','auto',1,0,0,datetime('now'))")
    con.execute("insert into source_links(item_id,retailer_id,url,status,consecutive_failures,created_at,last_price_cents)"
                " values(1,1,'https://a.ca/x','confirmed',0,datetime('now'),1999)")
    con.execute("insert into observations(item_id,source_link_id,observed_at,price_cents,currency,method)"
                " values(1,1,datetime('now'),1999,'CAD','http')")
    con.execute("insert into alerts(item_id,rule_type,dedup_key,title,body,status,created_at)"
                " values(1,'target','k','t','b','sent',datetime('now'))")
    con.commit()
    con.close()

    command.upgrade(alembic_config(url), "head")

    con = sqlite3.connect(db)
    assert con.execute("select count(*) from source_links").fetchone()[0] == 1
    assert con.execute("select count(*) from observations").fetchone()[0] == 1
    assert con.execute("select count(*) from alerts").fetchone()[0] == 1
    assert con.execute("select channel, condition from observations").fetchone() == ("online", "new")
    assert con.execute("pragma foreign_key_check").fetchall() == []


def test_upgrade_moves_data_to_admin_and_default_list(tmp_path):
    import hashlib
    import json

    db = tmp_path / "v03.db"
    url = f"sqlite:///{db}"
    command.upgrade(alembic_config(url), "0003")
    con = sqlite3.connect(db)
    cols = ("name,condition,priority,hot,active,exclude_refurbished,exclude_open_box,exclude_used,"
            "exclude_marketplace,exclude_bundles,exclude_variants,autofill,created_at,updated_at,snoozed_until")
    con.execute(f"insert into items({cols}) values ('TV','new',3,0,1,1,1,1,1,1,1,0,datetime('now'),datetime('now'),"
                "datetime('now','+1 day'))")
    con.execute("insert into settings(key,value) values ('province', ?), ('notify_urls', ?), ('api_token', ?),"
                " ('fake_sale_pct', ?)",
                (json.dumps("QC"), json.dumps(["ntfys://ntfy.sh/x"]), json.dumps("tok123"), json.dumps(7)))
    con.commit()
    con.close()

    command.upgrade(alembic_config(url), "head")

    con = sqlite3.connect(db)
    uid, role, pw = con.execute("select id, role, password_hash from users").fetchone()
    assert role == "admin" and pw is None
    lid = con.execute("select list_id from items").fetchone()[0]
    assert con.execute("select role from list_members where list_id=? and user_id=?", (lid, uid)).fetchone()[0] == "owner"
    us = dict(con.execute("select key, value from user_settings where user_id=?", (uid,)).fetchall())
    assert json.loads(us["province"]) == "QC" and json.loads(us["notify_urls"]) == ["ntfys://ntfy.sh/x"]
    glob = dict(con.execute("select key, value from settings").fetchall())
    assert "province" not in glob and json.loads(str(glob["fake_sale_pct"])) == 7
    assert con.execute("select api_token_hash from users").fetchone()[0] == hashlib.sha256(b"tok123").hexdigest()
    assert con.execute("select count(*) from user_item_prefs").fetchone()[0] == 1
