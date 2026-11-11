# ShareFlow — Django prototype

A local, simulated prototype of the peer-to-peer share bidding and allocation workflow described in the supplied system overview.

## Requirements
- Python 3.10+
- pip

## Setup (Windows CMD)
```bat
cd share_bidding_prototype
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
py manage.py migrate
py manage.py seed_demo
py manage.py createsuperuser
py manage.py runserver
```
Open http://127.0.0.1:8000/

Demo login:
- Username: `demo_member`
- Password: `DemoPass123!`

Admin:
- Open http://127.0.0.1:8000/admin/
- Sign in with the superuser created above.

## Prototype workflow
1. Register or sign in.
2. Submit a purchase request while an administrator-created session is open.
3. In Django admin, review Purchase Requests and use the action to accept selected requests and create holdings.
4. In Django admin, select due Holding records and run the maturity processing action.
5. In Django admin, use the Allocation action to match submitted purchase requests against available matured listings.
6. Buyer submits M-Pesa payment evidence from Sold Shares.
7. Seller records receipt confirmation or either party raises a dispute.

## Important prototype limitations
- No live M-Pesa/STK Push, bank connection, SMS or email integration.
- No real funds are accepted, stored, transferred or verified.
- The allocation admin action is a demonstration workflow and needs production-grade policy, validation, database locking, idempotency and automated tests before use.
- Maturity processing is manually triggered through Django admin in this prototype.
- Session open/close state is controlled by admin; the browser must never be treated as authoritative.
- The proposed 3-day/6%, 7-day/12%, and 14-day/20% rates are illustrative only. They are not validated or guaranteed.
- The demo uses SQLite. PostgreSQL is recommended for concurrent transactions and production.
- The sample admin actions are for controlled demonstration, not live financial operations.

## Before any real-money pilot
Obtain qualified Kenyan legal and compliance advice on product classification, funding source, disclosures, consumer protection, data protection and relevant regulatory approvals. Implement independently verified payment reconciliation, role-based review, strong audit controls, concurrency tests, backups and a tested incident/dispute process.
