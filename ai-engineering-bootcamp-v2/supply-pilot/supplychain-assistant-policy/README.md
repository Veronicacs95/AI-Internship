# NovaTech Retail --- SupplyPilot RAG Corpus

Fictional internal supply-planning policy pack for the SupplyPilot AI
capstone.

This corpus is designed to support RAG retrieval, grounded answers,
citations, refusal testing, and later agent/tool workflows for inventory
and replenishment analysis.

## Capstone goal

**SupplyPilot** is an AI inventory and supply-planning copilot for a
fictional consumer-electronics retailer. It answers planning-policy
questions and, in later stages, combines policy knowledge with
structured inventory, forecast, purchase-order, and supplier data to
support replenishment decisions.

For the initial version, NovaTech operates as a **single combined
inventory and demand pool** across online and physical retail channels.
Location-specific inventory, store allocation, safety stock, and
multi-warehouse planning are intentionally deferred to later versions.

## Teaching facts preserved

  -------------------------------------------------------------------------------------------------------------
  Doc ID         File                                            Policy          Must-keep facts
  -------------- ----------------------------------------------- --------------- ------------------------------
  POL-101        `POL-101_inventory_coverage_wos.txt`            Inventory       **WOS = Available Inventory /
                                                                 Coverage & WOS  Average Weekly Demand**;
                                                                                 target **4--6 WOS**; below **4
                                                                                 WOS** = below target; below
                                                                                 **2 WOS** = critical; above
                                                                                 **8 WOS** = potential
                                                                                 overstock. WOS alone must
                                                                                 **not** automatically trigger
                                                                                 replenishment.

  POL-102        `POL-102_demand_forecast_management.txt`        Demand &        Approved **weekly forecast**
                                                                 Forecast        is the primary forward-looking
                                                                 Management      demand signal; historical
                                                                                 sales are supporting evidence;
                                                                                 a variance greater than
                                                                                 **20%** between the most
                                                                                 recent **4-week average actual
                                                                                 sales** and corresponding
                                                                                 average forecast is material
                                                                                 and triggers review; actual
                                                                                 sales do not automatically
                                                                                 replace forecast.

  POL-103        `POL-103_replenishment_decision.txt`            Replenishment   Standard recommendations are
                                                                 Decision Policy **Increase, Maintain, Reduce,
                                                                                 Delay**. Decisions must
                                                                                 consider future inventory,
                                                                                 demand, incoming supply,
                                                                                 arrival timing, lead time, and
                                                                                 supplier constraints. Current
                                                                                 WOS alone is insufficient.

  POL-104        `POL-104_purchase_orders_incoming_supply.txt`   Purchase Orders Open PO does not automatically
                                                                 & Incoming      equal confirmed supply.
                                                                 Supply          Confirmed incoming supply
                                                                                 requires a valid/acknowledged
                                                                                 order, outstanding quantity,
                                                                                 valid expected arrival date,
                                                                                 and no cancelled/on-hold
                                                                                 status. Incoming supply is
                                                                                 **time-dependent** and must
                                                                                 not be treated as inventory
                                                                                 available today.

  POL-105        `POL-105_supplier_ordering_constraints.txt`     Supplier        **MOQ** is the minimum
                                                                 Ordering        acceptable order quantity;
                                                                 Constraints     **order multiples** define
                                                                                 valid increments. Constraints
                                                                                 can differ by SKU/supplier and
                                                                                 belong in structured
                                                                                 product/supplier data.
                                                                                 Supplier constraints determine
                                                                                 what NovaTech **can order**,
                                                                                 not what it **should order**.

  POL-106        `POL-106_lead_time_stockout_expedite.txt`       Lead Time,      Lead time varies by
                                                                 Stockout Risk & SKU/supplier. Expedite should
                                                                 Expedite        be considered when projected
                                                                                 stockout occurs **before** the
                                                                                 next confirmed or feasible
                                                                                 standard supply arrival and
                                                                                 the gap is a material business
                                                                                 risk. Low/critical WOS alone
                                                                                 does **not** automatically
                                                                                 require expedite.
  -------------------------------------------------------------------------------------------------------------

## Knowledge vs structured data

The RAG corpus contains **business knowledge and planning rules**.

Examples:

-   WOS thresholds
-   how forecasts should be interpreted
-   how incoming POs should be treated
-   replenishment decision principles
-   how MOQ/order multiples should be applied
-   when an expedite should be considered

Changing operational facts should **not** be stored in the RAG corpus.

These belong in structured data such as CSV or a database:

-   current inventory
-   weekly SKU forecast
-   historical sales
-   open purchase orders
-   expected arrival dates
-   SKU-specific MOQ
-   order multiples
-   supplier lead times

This separation is intentional so later versions of SupplyPilot can
combine RAG with deterministic tools.

## Suggested golden-set questions

### POL-101 --- Inventory Coverage & WOS

1.  What is NovaTech's target WOS? → **4--6 weeks** → POL-101
2.  When is inventory considered critical? → **Below 2 WOS** → POL-101
3.  When is inventory considered potential overstock? → **Above 8 WOS**
    → POL-101
4.  Does inventory below 4 WOS automatically mean NovaTech should place
    another PO? → **No** → POL-101

### POL-102 --- Demand & Forecast Management

5.  What is the primary forward-looking demand signal? → **Approved
    weekly forecast** → POL-102
6.  When is forecast variance considered material? → **Greater than 20%
    using the most recent four-week average actual sales versus
    corresponding average forecast** → POL-102
7.  Should one unusually high sales week automatically replace the
    approved forecast? → **No** → POL-102

### POL-103 --- Replenishment Decision Policy

8.  What are NovaTech's four replenishment recommendation categories? →
    **Increase, Maintain, Reduce, Delay** → POL-103
9.  When should NovaTech consider increasing replenishment? → **When
    projected coverage remains below target and confirmed incoming
    supply is insufficient, considering lead time and constraints** →
    POL-103
10. What is the difference between reducing and delaying replenishment?
    → **Reduce changes quantity; delay moves required supply to a later
    arrival** → POL-103

### POL-104 --- Purchase Orders & Incoming Supply

11. Can every open PO be treated as confirmed incoming supply? → **No**
    → POL-104
12. Should supply arriving in three weeks be counted as inventory
    available today? → **No** → POL-104
13. What quantity remains incoming after 600 units of a 1,000-unit PO
    are received? → **400 units** → POL-104

### POL-105 --- Supplier Ordering Constraints

14. What is MOQ? → **Minimum Order Quantity** → POL-105
15. If MOQ is 500 and the order multiple is 100, is 550 a valid standard
    order quantity? → **No** → POL-105
16. Are MOQ and order multiples the same for every NovaTech SKU? →
    **No** → POL-105
17. Do supplier constraints determine what NovaTech should order? →
    **No; they determine what can be ordered** → POL-105

### POL-106 --- Lead Time, Stockout Risk & Expedite

18. When should an expedite be considered? → **When projected stockout
    occurs before confirmed/feasible standard supply arrival and the gap
    represents material business risk** → POL-106
19. Does critical WOS automatically require an expedite? → **No** →
    POL-106
20. Can a SKU with healthy current WOS still face future stockout risk?
    → **Yes, if remaining coverage is shorter than the time until
    replacement supply can become available** → POL-106

## Cross-document questions

These questions are intentionally more difficult and may require
retrieval from more than one policy.

21. A SKU has 2 WOS but sufficient confirmed supply arrives next week.
    Should NovaTech automatically place another PO? → **No; evaluate
    incoming supply and projected coverage** → POL-101, POL-103, POL-104

22. Sales have been 25% above forecast for four weeks and projected
    coverage is below target. What should be reviewed? → **Forecast and
    replenishment position** → POL-102, POL-103

23. A SKU will stock out in three weeks but confirmed supply arrives in
    five weeks. What risk exists? → **Approximately two weeks of
    stockout exposure; expedite/replenishment review may be
    appropriate** → POL-104, POL-106

24. The calculated requirement is 420 units but the SKU has MOQ 500 and
    order multiple 100. What is the smallest standard executable
    quantity? → **500 units**, subject to projected-inventory validation
    → POL-105

## Refusal / insufficient-information questions

These facts are intentionally **not defined in the initial corpus**. The
assistant should refuse or state that it does not have enough
information rather than inventing an answer.

25. What safety-stock quantity should NovaTech hold for SKU HPH-501? →
    **Not defined**
26. How much inventory is currently available for HPH-501? → **Not in
    policy corpus; requires structured inventory data**
27. What is the current open PO quantity for LAP-101? → **Not in policy
    corpus; requires structured PO data**
28. Which NovaTech store has the highest inventory? → **Not defined; V1
    uses one combined inventory pool**
29. What is the warehouse buffer policy? → **Not defined in V1**
30. What is the exact MOQ for HPH-501? → **Not in policy corpus;
    requires structured SKU/supplier data**

These questions are useful for testing whether the RAG assistant
distinguishes **policy knowledge** from information that should come
from future tools or structured databases.

## Current RAG configuration

Initial retrieval experiments use:

-   Embedding model: `text-embedding-3-small`
-   Embedding dimensions: `512`
-   Chunk size: `800` characters
-   Chunk overlap: `100` characters
-   Vector database: Pinecone
-   Retrieval: top-k similarity search

These values are initial experimental settings, not assumed optimal
settings. Chunking and retrieval should be evaluated against the golden
set before being changed.

## Planned progression

**V1 --- Policy RAG**

Answer NovaTech planning-policy questions with grounded responses,
citations, and refusal when the corpus does not contain the answer.

**V2 --- Structured supply data + deterministic tools**

Add inventory, forecast, sales, open-PO, supplier, and product data.
Introduce tools such as:

-   `get_product_data()`
-   `get_inventory()`
-   `get_forecast()`
-   `get_open_pos()`
-   `calculate_wos()`

**V3 --- Single tool-using agent**

Allow one agent to decide which policy retrieval and deterministic tools
are required to answer supply-planning questions.

**V4 --- Workflow/orchestration**

Reimplement or expand the agent workflow using an orchestration
framework once the raw agent/tool behavior is understood.

**Later extensions**

Potential future scope includes safety stock, reorder points,
store/warehouse inventory, allocation, multiple locations, supplier
risk, multi-client support, and multi-agent routing.

## Suggested folder structure

``` text
novatech-sample-docs/
├── README.md
├── POL-101_inventory_coverage_wos.txt
├── POL-102_demand_forecast_management.txt
├── POL-103_replenishment_decision.txt
├── POL-104_purchase_orders_incoming_supply.txt
├── POL-105_supplier_ordering_constraints.txt
└── POL-106_lead_time_stockout_expedite.txt
```

## Notes

-   NovaTech Retail is fictional.
-   All policies and future operational data are synthetic and created
    for educational purposes.
-   Policy documents describe business rules; changing operational
    values should come from structured data.
-   The corpus is intentionally small so retrieval behavior can be
    understood and evaluated before adding complexity.
