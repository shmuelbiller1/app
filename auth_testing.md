# Auth Testing Playbook

## Credentials
- Admin: admin@tokenforge.io / Admin@12345 (role admin)
- Register a normal user at /api/auth/register

## Step 1: MongoDB Verification
```
mongosh
use test_database
db.users.find({role: "admin"}).pretty()
db.users.findOne({role: "admin"}, {password_hash: 1})
```
Verify bcrypt hash starts with `$2b$`. Indexes: users.email unique, api_keys.key_hash unique.

## Step 2: API Testing
```
API=https://token-optimizer-14.preview.emergentagent.com
curl -c cookies.txt -X POST $API/api/auth/login -H "Content-Type: application/json" -d '{"email":"admin@tokenforge.io","password":"Admin@12345"}'
curl -b cookies.txt $API/api/auth/me
```
Login returns user object and sets access_token + refresh_token cookies.

## Step 3: Optimizer
- Create API key: POST /api/keys {name} -> returns api_key (tio_...)
- Programmatic: POST /api/v1/optimize with X-API-Key header and {text}
- File job: POST /api/jobs (multipart file) -> poll GET /api/jobs/{id} until status completed
- Fragments: GET /api/jobs/{id}/fragments?page=1&search=
- Export: GET /api/jobs/{id}/export
