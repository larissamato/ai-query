\getenv reader_password AI_QUERY_PASSWORD
-- Evita registrar a instrução parametrizada mesmo se a criação do papel falhar.
SET LOCAL log_statement = 'none';
SET LOCAL log_min_error_statement = 'panic';
CREATE ROLE ai_query_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'reader_password';
\unset reader_password

REVOKE ALL ON DATABASE ai_query FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE ai_query TO ai_query_reader;
GRANT USAGE ON SCHEMA ecommerce TO ai_query_reader;
GRANT SELECT ON ecommerce.customers, ecommerce.categories, ecommerce.products,
    ecommerce.orders, ecommerce.order_items TO ai_query_reader;

ALTER ROLE ai_query_reader IN DATABASE ai_query SET search_path = ecommerce, pg_catalog;
ALTER ROLE ai_query_reader IN DATABASE ai_query SET default_transaction_read_only = on;
