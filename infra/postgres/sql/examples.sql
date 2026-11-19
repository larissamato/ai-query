SELECT date_trunc('month', ordered_on::timestamp)::date AS month,
       count(*) AS orders,
       count(*) FILTER (WHERE status = 'cancelled') AS cancelled
FROM ecommerce.orders
GROUP BY 1
ORDER BY 1;

SELECT c.name AS category, sum(i.quantity) AS units,
       sum(i.quantity * i.unit_price) AS sales
FROM ecommerce.order_items AS i
JOIN ecommerce.orders AS o USING (order_id)
JOIN ecommerce.products AS p USING (product_id)
JOIN ecommerce.categories AS c USING (category_id)
WHERE o.status IN ('paid', 'shipped')
GROUP BY c.category_id, c.name
ORDER BY sales DESC, category;
