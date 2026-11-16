# Home Assistant

PriceWatch exposes compact JSON for Home Assistant REST sensors. Each person's sensors show their own lists.

## 1. Create a token

In PriceWatch: Settings, Your account, Create token. Copy it once; it is stored hashed.
In Home Assistant, add it to `secrets.yaml`:

```yaml
pricewatch_token: "Bearer <your token>"
```

## 2. Sensors (`configuration.yaml`)

```yaml
rest:
  - resource: http://192.168.2.15:8086/api/ha/summary
    headers:
      Authorization: !secret pricewatch_token
    scan_interval: 300
    sensor:
      - name: PriceWatch buy now
        unique_id: pricewatch_buy_now
        value_template: "{{ value_json.state }}"
        unit_of_measurement: items
        icon: mdi:tag-arrow-down
        json_attributes:
          - buy_now
          - buy
          - buy_and_protect
          - wait
          - stale
          - sale_mode
          - items
      - name: PriceWatch claimable
        unique_id: pricewatch_claimable
        value_template: "{{ value_json.claimable }}"
        unit_of_measurement: CAD
        device_class: monetary
        icon: mdi:cash-refund
```

Use the address and port your Home Assistant can reach (LAN IP or the Tailscale name). One request every
5 minutes reads the database only; it never triggers retailer checks.

## 3. Example automation

```yaml
automation:
  - alias: PriceWatch new buy
    trigger:
      - platform: state
        entity_id: sensor.pricewatch_buy_now
    condition:
      - "{{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}"
    action:
      - service: notify.mobile_app_phone
        data:
          title: PriceWatch
          message: "Buy now: {{ state_attr('sensor.pricewatch_buy_now', 'buy_now') | join(', ') }}"
```

## One item

`GET /api/ha/items/<id>` returns one item: `price` (landed, CAD), `price_before_tax`, `seasonal_low`, `target`,
`badge`, `decision`, `retailer`, `store_url`, `url`, `confidence`, `stale`.

```yaml
rest:
  - resource: http://192.168.2.15:8086/api/ha/items/12
    headers:
      Authorization: !secret pricewatch_token
    scan_interval: 600
    sensor:
      - name: Headphones price
        value_template: "{{ value_json.price }}"
        unit_of_measurement: CAD
        json_attributes: [badge, seasonal_low, target, retailer, store_url]
```
