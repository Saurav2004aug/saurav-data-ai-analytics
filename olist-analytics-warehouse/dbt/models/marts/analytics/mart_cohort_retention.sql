-- Monthly acquisition cohorts: share of each cohort that ordered again N months later.
-- Cohort = month of the customer's first non-canceled order.
with activity as (
    select distinct customer_unique_id, order_month
    from {{ ref('fct_orders') }}
    where is_canceled = 0
),

customers as (
    select customer_unique_id, min(order_month) as cohort_month
    from activity
    group by customer_unique_id
),

cohort_activity as (
    select
        customers.cohort_month,
        {{ dbt.datediff('customers.cohort_month', 'activity.order_month', 'month') }} as months_since_first,
        count(distinct activity.customer_unique_id)                                  as active_customers
    from activity
    inner join customers on activity.customer_unique_id = customers.customer_unique_id
    group by 1, 2
),

cohort_size as (
    select cohort_month, count(*) as cohort_customers
    from customers
    group by cohort_month
)

select
    cohort_activity.cohort_month,
    cohort_activity.months_since_first,
    cohort_size.cohort_customers,
    cohort_activity.active_customers,
    {{ safe_divide('cohort_activity.active_customers', 'cohort_size.cohort_customers') }} as retention_rate
from cohort_activity
inner join cohort_size on cohort_activity.cohort_month = cohort_size.cohort_month
