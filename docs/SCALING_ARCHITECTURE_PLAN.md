# Next-Generation Scaling Architecture & Execution Plan

This document outlines the architectural shift from our MVP (single-run, one-shot pipeline) to an enterprise-ready system capable of handling **Bulk AOI Processing (200+ polygons)**, **Scheduled Monitoring**, and **Team Workspaces**.

It is designed for developers to understand *why* we are making these changes, *how* the moving parts fit together, and the *exact order* in which to tackle the open GitHub Issues.

---

## 1. The "Why": Current Bottlenecks & Constraints

The existing MVP architecture uses **Azure Blob Storage** as a pseudo-database for state and relies on a standard **Azure Durable Function** worker to loop through all geospatial clipping and processing locally. This breaks under scale for two reasons:

1. **The DB Problem:** Blob storage cannot efficiently handle complex querying (needed for *User Dashboards* & *EUDR Temporal mapping*) or secure multi-tenant pathing (needed for *Team Workspaces*). Furthermore, it fails under high-concurrency state-machine tracking.
2. **The Compute Problem:** Processing 200+ high-res STAC imagery polygons sequentially or locally via `rasterio` will trigger Python memory leaks, blow past the 1.5GB Azure Function memory limit, and crash the runtime.

Because we are pre-revenue, we cannot simply throw money at big provisioned VMs or expensive hosted databases. We must maintain a **Scale-to-Zero ($0 base cost)** posture while safely absorbing massive bursts of concurrent compute.

---

## 2. The "How": Architectural Solutions

To unblock the product roadmap, we are implementing a hybrid, highly-concurrent architecture:

* **Azure Cosmos DB Serverless (#319):** Replaces Blob Storage for metadata and state. It costs nothing when idle but effortlessly absorbs 200 concurrent HTTP reads/writes during a massive burst run.
* **Fan-out/Fan-in orchestration (#316):** Instead of looping 200 AOIs in one Function, the orchestrator triggers 200 separate worker Functions simultaneously (one per AOI).
* **The Claim Check Pattern:** To avoid Azure's 48 KiB payload limits, the orchestrator only passes `aoi_id` references to the workers. The workers use the ID to query Cosmos DB for their specific geometry.
* **Rust / PyO3 Hotspots (#317):** Specific memory-heavy geometry math functions are rewritten in safe, compiled Rust and called from Python to keep our worker footprint flat and predictable.
* **Tiered Compute Fallback (#315):** If a single AOI is truly massive (e.g., 100,000 hectares), we route it to an Azure Batch Spot VM instead of the standard serverless pool.

---

## 3. Execution Order (The Dependency Graph)

To ensure smooth delivery, developers should pick up tasks in the following phased order. **Do not start the next phase until the previous is complete.**

### Phase 0: Baseline & Load Testing

Before writing any new scaling code, we must empirically define our breaking points.

* **[#320] Establish Load Testing Baseline:** Utilize tools (like `scripts/perf_test.py` or Locust/k6) to simulate 1, 50, and 200+ concurrent AOI requests.
* **The Goal:** Measure exactly when standard Azure Functions hit OOM (Out of Memory) or timeout, and when Blob Storage starts throttling. This baseline will justify the execution of Phase 1 and 2.

### Phase 1: The Data Foundation

Before we can fan out compute or build dashboards, we need our proper data layer.

* **[#319] Cosmos DB Infrastructure:** Provision Cosmos DB Serverless via OpenTofu in `infra/tofu/`.
* **[#314] DB Migration & Refactor:** Update `blueprints/` and `treesight/storage/` to write Runs, AOIs, and User State to Cosmos DB instead of Blob prefixes. Ensure the schema supports a `tenant_id` for future team segregation.
* **Data Modeling (Pydantic V2):** Because Cosmos DB is a schemaless NoSQL store, aggressively use **Pydantic V2** to define strict schemas (`AOIModel`, `RunState`, etc.). *Note: Pydantic V2's core validation engine is written in Rust, giving us compiled-level performance for JSON hydration without writing custom Rust code.*
* **GeoJSON Serialization:** Use Rust-backed Python libraries like `orjson` to parse the massive KML/GeoJSON text blobs coming in and out of the database, as the standard Python `json` library is too slow for high-concurrency payloads.

### Phase 2: Compute & Orchestration Refactor

Once the DB can handle concurrent reads/writes and act as a state machine, rebuild the backend engine.

* **[#316] Implement Fan-out / Claim Check:** Refactor `blueprints/pipeline.py` to fan out tasks using the new Cosmos DB `aoi_id`s.
* **[#317] Rust (PyO3) Optimizations:** Identify memory hotspots in `treesight/geo.py` and rewrite in Rust to prevent the fanned-out workers from crashing.
* **[#318] Spike: Bulk Image Strategy:** Research and decide how we will return 200 images to the frontend (Individual vs. Mosaic).
* **[#315] (Optional for now) Azure Batch Fallback:** Only build this Spot VM routing when we encounter an AOI too big for Phase 2's Rust workers.

### Phase 3: The Product Features

With the backend scaling infinitely and safely, developers can easily ship the frontend / API feature work.

* **[#311] Bulk AOI Uploads:** Allow the UI to submit KMLs with multiple shapes.
* **[#312] User Dashboards:** Query Cosmos DB to show users their historical EUDR compliance runs.
* **[#313] Team Workspaces:** Alter CIAM/auth and DB queries to partition by Team instead of individual User.
* **[#310] Scheduled Monitoring:** Build cron jobs that automatically re-trigger runs against Cosmos DB `Subscription` records.

---

## 4. Future Horizion: Python 3.13 & Free-Threading

While the current architecture targets **Python 3.12**, Python 3.13 introduces experimental "Free-Threading" (the removal of the Global Interpreter Lock or GIL).

* **The Opportunity:** Free-threading could eventually allow us to utilize multi-core Azure workers for CPU-bound geospatial math safely without the heavy overhead of Python's `multiprocessing` library.
* **The Current Risk:** We are keeping this off the immediate critical path because the **Azure Functions runtime** and heavily C-bound libraries like **Rasterio/GDAL** historically take months (or years) to become fully stable with no-GIL Python. Furthermore, our Serverless Fan-Out architecture already bypasses the GIL by spinning up separate isolated worker VMs. We will re-evaluate Python 3.13 when Azure officially declares long-term support for its Durable Functions worker on it.
