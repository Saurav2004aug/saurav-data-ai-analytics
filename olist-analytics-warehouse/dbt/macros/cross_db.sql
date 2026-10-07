{#-
  Small cross-database helpers, written with adapter.dispatch so the same models run on
  DuckDB / MotherDuck (default__), and on SQLite (sqlite__, used by the offline test
  harness in tests/). Add a snowflake__ or bigquery__ variant to port the project.
-#}

{% macro date_part_int(part, expr) -%}
    {{ return(adapter.dispatch('date_part_int', 'olist_analytics')(part, expr)) }}
{%- endmacro %}

{% macro default__date_part_int(part, expr) -%}
    cast(extract({{ part }} from {{ expr }}) as integer)
{%- endmacro %}

{% macro sqlite__date_part_int(part, expr) -%}
    {%- set fmt = {'year': '%Y', 'month': '%m', 'day': '%d', 'dow': '%w'} -%}
    {%- if part == 'quarter' -%}
        ((cast(strftime('%m', {{ expr }}) as integer) + 2) / 3)
    {%- else -%}
        cast(strftime('{{ fmt[part] }}', {{ expr }}) as integer)
    {%- endif -%}
{%- endmacro %}


{% macro to_date(expr) -%}
    {{ return(adapter.dispatch('to_date', 'olist_analytics')(expr)) }}
{%- endmacro %}

{% macro default__to_date(expr) -%}
    cast({{ expr }} as date)
{%- endmacro %}

{% macro sqlite__to_date(expr) -%}
    date({{ expr }})
{%- endmacro %}


{% macro safe_divide(numerator, denominator) -%}
    case when ({{ denominator }}) is null or ({{ denominator }}) = 0 then null
         else 1.0 * ({{ numerator }}) / ({{ denominator }}) end
{%- endmacro %}
