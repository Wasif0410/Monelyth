
639 rows, 53 distinct merchants

| Baseline | Accuracy (rows) | Accuracy (merchants) | Fires on (merchants) | Right when it fires |
|---|---|---|---|---|
| Majority class (Coffee) | 32.9% | 9.4% | 100% | 9.4% |
| Keywords: generic (else majority) | 67.8% | 58.5% | 54.7% | 96.6% |
| Keywords: brands (else majority) | 100.0% | 100.0% | 98.1% | 100.0% |

| Variant | Acc. rows | Acc. merchants (95% CI) | Shipped conf>=0.8: cov / acc | Recalibrated conf>=0.8: cov / acc | ECE shipped / recal. |
|---|---|---|---|---|---|
| laya__json__described | 29.7% | 22.6% (13.5%-35.5%) | 71.7% / 18.4% | 0.0% / n/a | 0.637 / 0.154 |
| laya__json__names | 29.0% | 22.6% (13.5%-35.5%) | 90.6% / 18.8% | 0.0% / n/a | 0.742 / 0.148 |
| laya__merchant__names | 21.3% | 26.4% (16.4%-39.6%) | 13.2% / 57.1% | 3.8% / 100.0% | 0.186 / 0.137 |
| laya__plain__names | 52.4% | 50.9% (37.9%-63.9%) | 71.7% / 63.2% | 24.5% / 76.9% | 0.346 / 0.174 |
| laya__sentence__described | 41.5% | 43.4% (31.0%-56.7%) | 54.7% / 62.1% | 5.7% / 66.7% | 0.322 / 0.136 |
| laya__sentence__names | 48.7% | 47.2% (34.4%-60.3%) | 69.8% / 56.8% | 15.1% / 50.0% | 0.384 / 0.175 |
| laya__text__described | 26.1% | 20.8% (12.0%-33.5%) | 58.5% / 22.6% | 1.9% / 0.0% | 0.574 / 0.083 |
| laya__text__names | 26.1% | 24.5% (14.9%-37.6%) | 66.0% / 28.6% | 1.9% / 0.0% | 0.609 / 0.130 |
| typed-decisions-onnx-fp32__plain__names | 53.1% | 52.8% (39.7%-65.6%) | 45.3% / 66.7% | 18.9% / 70.0% | 0.258 / 0.142 |
| typed-decisions-onnx-int8__plain__names | 51.8% | 41.5% (29.3%-54.9%) | 39.6% / 61.9% | 5.7% / 100.0% | 0.257 / 0.177 |
| typed-decisions__json__described | 36.3% | 26.4% (16.4%-39.6%) | 28.3% / 46.7% | 0.0% / n/a | 0.403 / 0.101 |
| typed-decisions__json__names | 30.7% | 24.5% (14.9%-37.6%) | 28.3% / 26.7% | 0.0% / n/a | 0.442 / 0.075 |
| typed-decisions__merchant__names | 25.0% | 20.8% (12.0%-33.5%) | 1.9% / 100.0% | 0.0% / n/a | 0.155 / 0.096 |
| typed-decisions__plain__names | 53.1% | 52.8% (39.7%-65.6%) | 45.3% / 66.7% | 18.9% / 70.0% | 0.258 / 0.142 |
| typed-decisions__sentence__described | 43.5% | 39.6% (27.6%-53.1%) | 28.3% / 73.3% | 1.9% / 0.0% | 0.236 / 0.134 |
| typed-decisions__sentence__names | 46.9% | 41.5% (29.3%-54.9%) | 47.2% / 68.0% | 1.9% / 0.0% | 0.286 / 0.182 |
| typed-decisions__text__described | 31.3% | 26.4% (16.4%-39.6%) | 9.4% / 60.0% | 0.0% / n/a | 0.310 / 0.052 |
| typed-decisions__text__names | 31.5% | 30.2% (19.5%-43.5%) | 18.9% / 40.0% | 0.0% / n/a | 0.302 / 0.120 |

Best variant by merchant accuracy: typed-decisions__plain__names


#### per_merchant: selective accuracy

| Threshold | Shipped: coverage | accuracy | wrong | Recal.: coverage | accuracy | wrong |
|---|---|---|---|---|---|---|
| >= 0.50 | 73.6% | 61.5% | 15 | 47.2% | 68.0% | 8 |
| >= 0.80 | 45.3% | 66.7% | 8 | 18.9% | 70.0% | 3 |
| >= 0.90 | 37.7% | 65.0% | 7 | 0.0% | n/a | 0 |
| >= 0.95 | 26.4% | 64.3% | 5 | 0.0% | n/a | 0 |

Recalibration fold temperatures: [0.9070068176689573, 0.8670540889734764, 0.8541314966877566, 0.8165078721541141, 0.7923507420918469]

#### per_merchant: reliability (shipped)

| Confidence | Count | Mean confidence | Accuracy |
|---|---|---|---|
| 0.00-0.50 | 14 | 34.8% | 28.6% |
| 0.50-0.80 | 15 | 61.0% | 53.3% |
| 0.80-0.90 | 4 | 87.5% | 75.0% |
| 0.90-0.95 | 6 | 92.3% | 66.7% |
| 0.95-1.00 | 14 | 98.0% | 64.3% |

#### all_rows: selective accuracy

| Threshold | Shipped: coverage | accuracy | wrong | Recal.: coverage | accuracy | wrong |
|---|---|---|---|---|---|---|
| >= 0.50 | 78.7% | 60.0% | 201 | 56.5% | 70.6% | 106 |
| >= 0.80 | 55.2% | 70.8% | 103 | 26.1% | 77.2% | 38 |
| >= 0.90 | 37.9% | 80.6% | 47 | 3.6% | 100.0% | 0 |
| >= 0.95 | 27.2% | 78.2% | 38 | 0.0% | n/a | 0 |

Recalibration fold temperatures: [0.8288612373804823, 0.8043386217415815, 0.8043386217415815, 0.7923507420918469, 0.7132919023562151]

#### all_rows: reliability (shipped)

| Confidence | Count | Mean confidence | Accuracy |
|---|---|---|---|
| 0.00-0.50 | 136 | 36.9% | 27.2% |
| 0.50-0.80 | 150 | 58.3% | 34.7% |
| 0.80-0.90 | 111 | 86.6% | 49.5% |
| 0.90-0.95 | 68 | 92.7% | 86.8% |
| 0.95-1.00 | 174 | 98.1% | 78.2% |

#### Per-category recall (all rows)

| Category | Support | Recall |
|---|---|---|
| Salary | 26 | 100.0% |
| Other Income | 2 | 50.0% |
| Rent/Mortgage | 12 | 100.0% |
| Utilities | 48 | 20.8% |
| Groceries | 94 | 46.8% |
| Dining Out | 62 | 80.6% |
| Coffee | 210 | 59.0% |
| Transport | 32 | 0.0% |
| Gas | 6 | 100.0% |
| Rideshare | 30 | 100.0% |
| Shopping | 17 | 70.6% |
| Subscriptions | 36 | 0.0% |
| Entertainment | 6 | 100.0% |
| Health | 9 | 22.2% |
| Education | 2 | 100.0% |
| Travel | 3 | 33.3% |
| Fees & Interest | 13 | 100.0% |
| Gifts & Donations | 3 | 0.0% |
| Transfers | 22 | 0.0% |
| Other | 6 | 0.0% |

#### Most common confusions (all rows): actual -> predicted

- Coffee -> Dining Out: 47
- Coffee -> Other: 38
- Subscriptions -> Entertainment: 36
- Transport -> Other: 32
- Groceries -> Other: 30
- Groceries -> Shopping: 20
- Utilities -> Gas: 14
- Utilities -> Coffee: 12
