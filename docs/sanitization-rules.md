# Sanitization Rules

## 1. Secret Patterns

Mask or remove content matching:
1. Access token and API key patterns
2. Private key blocks (`BEGIN ... PRIVATE KEY`)
3. Password-like assignments in config

## 2. Infra Privacy Patterns

Mask or remove:
1. Private IPs (`10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`)
2. Internal domains and host aliases
3. Internal absolute filesystem paths if they reveal private structure

## 3. Device Privacy Patterns

Mask or remove:
1. Real IMEI/ICCID/IMSI
2. Customer serial mappings
3. Production tenant identifiers

## 4. Required Mask Format

Use deterministic placeholders:
1. `<TOKEN>`
2. `<PRIVATE_IP>`
3. `<INTERNAL_DOMAIN>`
4. `<DEVICE_ID_MASKED>`
5. `<TENANT_ID_MASKED>`
