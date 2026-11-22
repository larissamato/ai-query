-- Run with psql --single-transaction and ON_ERROR_STOP.
SET LOCAL lock_timeout = '3s';
LOCK TABLE ecommerce.customers, ecommerce.categories, ecommerce.products,
           ecommerce.orders, ecommerce.order_items IN SHARE ROW EXCLUSIVE MODE;

WITH populated AS (
    SELECT EXISTS (SELECT FROM ecommerce.customers) AS has_rows
    UNION ALL SELECT EXISTS (SELECT FROM ecommerce.categories)
    UNION ALL SELECT EXISTS (SELECT FROM ecommerce.products)
    UNION ALL SELECT EXISTS (SELECT FROM ecommerce.orders)
    UNION ALL SELECT EXISTS (SELECT FROM ecommerce.order_items)
)
SELECT NOT bool_or(has_rows) AS empty_seed, bool_and(has_rows) AS populated_seed
FROM populated \gset

\if :empty_seed
    \ir seed.sql
    \echo Seed sintética aplicada ao schema vazio.
\elif :populated_seed
    \echo As cinco tabelas já têm dados. Carga existente preservada.
\else
    DO $$ BEGIN RAISE EXCEPTION 'Carga parcial detectada. Registros preservados. Revise o banco ou prepare um projeto isolado.'; END $$;
\endif
