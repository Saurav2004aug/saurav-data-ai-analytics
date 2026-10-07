-- Grain: one row per calendar day covering the data range.
with recursive spine as (
    select {{ to_date("'2016-01-01'") }} as date_day
    union all
    select {{ to_date(dbt.dateadd('day', 1, 'date_day')) }}
    from spine
    where date_day < {{ to_date("'2018-12-31'") }}
)

select
    date_day,
    {{ date_part_int('year', 'date_day') }}                         as year,
    {{ date_part_int('quarter', 'date_day') }}                      as quarter,
    {{ date_part_int('month', 'date_day') }}                        as month,
    {{ date_part_int('day', 'date_day') }}                          as day_of_month,
    {{ date_part_int('dow', 'date_day') }}                          as day_of_week,
    case when {{ date_part_int('dow', 'date_day') }} in (0, 6) then 1 else 0 end as is_weekend,
    {{ to_date(dbt.date_trunc('month', 'date_day')) }}              as month_start
from spine
