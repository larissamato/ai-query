\set ON_ERROR_STOP on

DO $$
BEGIN
    IF current_user <> 'ai_query_reader' OR current_setting('transaction_read_only') <> 'on' THEN
        RAISE EXCEPTION 'Execute a verificação com o usuário leitor em modo somente leitura';
    END IF;

    IF (SELECT count(*) FROM ecommerce.customers) <> 100
       OR (SELECT count(*) FROM ecommerce.categories) <> 10
       OR (SELECT count(*) FROM ecommerce.products) <> 100
       OR (SELECT count(*) FROM ecommerce.orders) <> 1000
       OR (SELECT count(*) FROM ecommerce.order_items) <> 3000 THEN
        RAISE EXCEPTION 'Contagens da carga sintética divergentes';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ecommerce.orders AS o
        LEFT JOIN ecommerce.customers AS c USING (customer_id)
        LEFT JOIN ecommerce.order_items AS i USING (order_id)
        WHERE c.customer_id IS NULL OR i.order_id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM ecommerce.products AS p
        LEFT JOIN ecommerce.categories AS c USING (category_id)
        WHERE c.category_id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM ecommerce.order_items AS i
        LEFT JOIN ecommerce.products AS p USING (product_id)
        LEFT JOIN ecommerce.orders AS o USING (order_id)
        WHERE p.product_id IS NULL OR o.order_id IS NULL OR i.unit_price <> p.price
    ) THEN
        RAISE EXCEPTION 'Relacionamentos ou preços históricos inconsistentes na carga';
    END IF;

    IF NOT (
        SELECT count(DISTINCT date_trunc('month', ordered_on::timestamp)) = 12
           AND date_trunc('month', max(ordered_on)::timestamp) =
               date_trunc('month', min(ordered_on)::timestamp) + interval '11 months'
        FROM ecommerce.orders
    ) THEN
        RAISE EXCEPTION 'A carga deve cobrir 12 meses consecutivos';
    END IF;

    IF has_database_privilege(current_database(), 'CREATE')
       OR has_database_privilege(current_database(), 'TEMP')
       OR has_schema_privilege('ecommerce', 'CREATE')
       OR has_schema_privilege('public', 'USAGE')
       OR EXISTS (
           SELECT 1 FROM (VALUES ('customers'), ('categories'), ('products'),
               ('orders'), ('order_items')) AS fixtures(table_name)
           WHERE has_table_privilege(
               'ecommerce.' || table_name,
               'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN'
           )
       ) THEN
        RAISE EXCEPTION 'O usuário leitor possui privilégios indevidos';
    END IF;
END $$;

-- Verifica a ACL mesmo com a proteção padrão de somente leitura desativada.
BEGIN READ WRITE;
DO $$
BEGIN
    BEGIN
        UPDATE ecommerce.orders SET status = 'paid' WHERE false;
        RAISE EXCEPTION 'A atualização deveria ser negada';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
END $$;
ROLLBACK;

SELECT 'Verificações concluídas' AS resultado;
