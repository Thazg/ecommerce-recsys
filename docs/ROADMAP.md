# Project roadmap

The project progresses from causal offline evaluation to retrieval, ranking and
serving. Each stage defines its scope and completion criteria before introducing
more complex models or infrastructure.

| Milestone | Scope | Completion criteria |
| :--- | :--- | :--- |
| M0–M2 | Foundation, dataset contract, quality and interaction semantics | Reproducible Retailrocket preparation and documented assumptions |
| M3 | Temporal evaluation | Shared rolling cohorts, causality and provenance guards |
| M4–M6 | Baselines, ItemKNN and implicit matrix factorization | Model comparisons with accuracy, availability and cost evidence |
| M7 | Candidate generation | Common retrieval interface, source attribution, and Recall@N, availability and cost measurements at requested budgets of 100, 500 and 1,000 candidates |
| M8 | Two-tower retrieval | Consistent train/inference features and recall comparison with exact ALS on shared temporal targets and catalogs |
| M9 | Approximate nearest neighbors, conditional on exact retrieval cost | Measured quality/speed trade-off against exact retrieval |
| M10–M11 | Ranking dataset, features and learned ranker | Causal examples, retrieval/ranking separation and Top-K comparison |
| M12 | Sequential recommendation (optional) | Measurable benefit from interaction order or recency |
| M13–M14 | Re-ranking, diversity and complete model benchmark | Documented relevance/coverage trade-offs and frozen model policy |
| M15–M17 | Artifact pipeline, service API, cache and fallbacks | Versioned artifacts, request contracts and reliable degraded behavior |
| M18–M22 | Observability, input safety, test strategy, containers and CI/CD | Reproducible deployment with operational checks |
| M23–M24 | Performance, load and failure testing | Full serving-path latency, memory and failure evidence |
| M25–M27 | Cloud design, deployment and post-deployment validation | Deployment justified by measured workload and verified behavior |
| M28–M29 | Public demo and final documentation | Explainable system, reproducible evidence and accurate limitations |
