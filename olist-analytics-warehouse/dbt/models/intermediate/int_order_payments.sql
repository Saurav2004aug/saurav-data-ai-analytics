-- One row per order: how it was paid.
with payments as (
    select * from {{ ref('stg_olist__payments') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by order_id order by payment_value desc, payment_sequential
        ) as value_rank
    from payments
)

select
    order_id,
    sum(payment_value)                                              as total_paid,
    count(*)                                                        as n_payments,
    max(case when value_rank = 1 then payment_type end)             as primary_payment_type,
    max(installments)                                               as max_installments,
    max(case when payment_type = 'voucher' then 1 else 0 end)       as used_voucher
from ranked
group by order_id
