# Order management API

A small Spring Boot service (customers, orders, order lines) backed by an
in-memory H2 database. It is the demo application whose pull requests are
reviewed by **Agentic Code Review with AgentCore x Temporal**: AI agents
orchestrated by Temporal and running as Serverless Workers on Amazon Bedrock
AgentCore.

## Run it

```bash
./mvnw spring-boot:run
```

The API listens on <http://localhost:8080> (set `PORT` to change it). Every
start fills the database with sample customers and orders:

```bash
curl http://localhost:8080/orders/1

curl -X POST http://localhost:8080/orders \
  -H 'Content-Type: application/json' \
  -d '{"customerId": 1, "lines": [{"product": "Notebook", "quantity": 2, "unitPriceCents": 450}]}'
```

## Test it

```bash
./mvnw test
```

## Demo references

| Reference | Role |
|---|---|
| `baseline` (tag) | State of `main` at the start of every demo |
| `scenario/customer-search` (tag) | The "Add customer search & order history" change |
| `feature/customer-search` (branch) | Opened as a pull request during the demo |
| `dev/customer-search` (branch) | Same change, reviewed by a local development worker |

The **Reset demo** workflow (Actions tab, "Run workflow") closes the open
pull requests, moves `main` back to `baseline` and recreates both branches
from the scenario tag. Tags never move.
