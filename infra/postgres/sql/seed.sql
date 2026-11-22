-- Versão ecommerce-v1. Altere a versão ao modificar a geração dos dados.
\getenv reference_date SEED_REFERENCE_DATE
SELECT COALESCE(
    NULLIF(:'reference_date', '')::date,
    date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
) AS reference_date \gset

SELECT (EXTRACT(DAY FROM :'reference_date'::date) = 1) AS valid_reference_date \gset
\if :valid_reference_date
\else
DO $$ BEGIN RAISE EXCEPTION 'SEED_REFERENCE_DATE deve ser o primeiro dia do mês'; END $$;
\endif

INSERT INTO ecommerce.customers (customer_id, name, email, city)
SELECT id, 'Cliente ' || id, 'cliente' || id || '@example.invalid',
       (ARRAY['São Paulo', 'Recife', 'Curitiba', 'Belém', 'Goiânia'])[1 + (id + 42) % 5]
FROM generate_series(1, 100) AS customers(id);

INSERT INTO ecommerce.categories (category_id, name)
SELECT id::integer, name
FROM unnest(ARRAY[
    'Livros', 'Eletrônicos', 'Cozinha', 'Esportes', 'Papelaria',
    'Jardinagem', 'Vestuário', 'Brinquedos', 'Decoração', 'Ferramentas'
]) WITH ORDINALITY AS categories(name, id);

INSERT INTO ecommerce.products (product_id, category_id, name, price)
SELECT id, 1 + (id + 42) % 10, 'Produto ' || id,
       (990 + (id * 7919 + 42) % 49000) / 100.0
FROM generate_series(1, 100) AS products(id);

-- O mesmo identificador e a mesma seed produzem os mesmos atributos.
-- A referência posiciona os pedidos em 12 meses completos, em UTC.
INSERT INTO ecommerce.orders (order_id, customer_id, ordered_on, status)
SELECT id, 1 + (id * 37 + 42) % 100,
       (:'reference_date'::date - make_interval(months => 1 + (id - 1) % 12))::date
           + ((id * 11 + 42) % 28),
       (ARRAY['pending', 'paid', 'paid', 'shipped', 'shipped', 'shipped', 'cancelled'])[
           1 + (id * 13 + 42) % 7
       ]
FROM generate_series(1, 1000) AS orders(id);

INSERT INTO ecommerce.order_items (order_id, product_id, quantity, unit_price)
SELECT orders.order_id, products.product_id,
       1 + (orders.order_id * 7 + item.position * 3 + 42) % 4, products.price
FROM ecommerce.orders
CROSS JOIN LATERAL generate_series(1, 1 + (orders.order_id + 42) % 5) AS item(position)
JOIN ecommerce.products
    ON products.product_id = 1 + (orders.order_id * 17 + item.position * 23 + 42) % 100;
