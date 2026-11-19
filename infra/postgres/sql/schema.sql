CREATE SCHEMA ecommerce;

CREATE TABLE ecommerce.customers (
    customer_id integer PRIMARY KEY,
    name text NOT NULL,
    email text NOT NULL UNIQUE,
    city text NOT NULL
);

CREATE TABLE ecommerce.categories (
    category_id integer PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE ecommerce.products (
    product_id integer PRIMARY KEY,
    category_id integer NOT NULL REFERENCES ecommerce.categories,
    name text NOT NULL,
    price numeric(10, 2) NOT NULL CHECK (price > 0),
    UNIQUE (category_id, name)
);

CREATE TABLE ecommerce.orders (
    order_id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES ecommerce.customers,
    ordered_on date NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled'))
);

CREATE TABLE ecommerce.order_items (
    order_id integer REFERENCES ecommerce.orders,
    product_id integer REFERENCES ecommerce.products,
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(10, 2) NOT NULL CHECK (unit_price > 0),
    PRIMARY KEY (order_id, product_id)
);

CREATE INDEX orders_customer_date_idx ON ecommerce.orders (customer_id, ordered_on);
CREATE INDEX orders_date_idx ON ecommerce.orders (ordered_on);
CREATE INDEX order_items_product_idx ON ecommerce.order_items (product_id);
