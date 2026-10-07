---
title: Operations - Delivery & Sellers
---

```sql delivery
select substr(delay_bucket, 4) as delay, orders, avg_review_score, one_star_rate
from olist.delivery_performance order by delay_bucket
```

## Delivery timing vs review score
<BarChart data={delivery} x=delay y=avg_review_score sort=false title="Average review by delivery delay"/>

```sql states
select state_code, region, orders, avg_delivery_days, late_delivery_rate, avg_review_score
from olist.state_performance where orders >= 30 order by avg_delivery_days desc
```

## By state
<BarChart data={states} x=state_code y=avg_delivery_days series=region sort=false title="Average delivery days"/>

```sql tiers
select tier, count(*) as sellers, sum(revenue) as revenue from olist.seller_scorecard group by tier
```

## Seller tiers
<DataTable data={tiers}/>

```sql attention
select seller_id, state_code, orders, revenue, avg_review_score, late_delivery_rate, avg_days_to_ship
from olist.seller_scorecard where tier = 'Needs attention' order by revenue desc limit 25
```

### Sellers needing attention
<DataTable data={attention} rows=10/>
