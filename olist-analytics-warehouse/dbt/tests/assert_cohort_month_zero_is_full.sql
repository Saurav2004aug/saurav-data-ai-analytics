-- By definition every cohort is 100% active in its first month (month 0).
select cohort_month, retention_rate
from {{ ref('mart_cohort_retention') }}
where months_since_first = 0
  and abs(retention_rate - 1.0) > 0.0001
