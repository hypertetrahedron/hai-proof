We use `sqlglot.executor.execute(sql, schema, tables=...)` to run SQL against small in-memory tables in tests and notebooks. It handles joins, aggregation and CTEs well. But when the optimizer can't turn a subquery into a join, the executor fails: queries whose `WHERE`, `HAVING` or `SELECT` list contain such a subquery raise `ExecuteError` or crash. That covers correlated `EXISTS` with an `OR`, a scalar subquery in the select list, `NOT IN (SELECT ...)`, and `> ANY (SELECT ...)`.

Please make the Python executor evaluate these subqueries itself. Results should match what DuckDB (or Postgres) returns for the same query and data, including NULL handling. Required support:

- **`EXISTS` / `NOT EXISTS`**, correlated or not. An empty subquery result means `EXISTS` is false.
- **Scalar subqueries** in the select list, in `WHERE` comparisons, and in `HAVING`. A scalar subquery that returns no rows evaluates to `NULL`. If it returns more than one row, raise `sqlglot.errors.ExecuteError`. If it selects more than one column, also raise `ExecuteError`. Detect the column case from the query itself, even when the outer table is empty and no outer row would ever evaluate the subquery.
- **`IN` / `NOT IN` with a subquery**, plus a scalar subquery used as an element of an `IN (...)` list or as the left-hand side of `IN`. Follow standard three-valued logic. If the subquery returns a `NULL` and there is no match, `x IN (...)` is `NULL` (so the row is filtered out), and `x NOT IN (...)` is also `NULL` (so the row is filtered out too).
- **`ANY` / `SOME` / `ALL`** with comparison operators (`a > ANY (SELECT ...)`, `a > ALL (...)`), again with standard NULL semantics. Over an empty set, `ANY` is false and `ALL` is true.
- **Correlation**: subqueries may reference columns of the enclosing query (`WHERE b = x.a`). This includes subqueries nested inside other subqueries that reference a table two levels out. When a name exists in both scopes, an inner table or alias takes precedence over the outer one.
- Subqueries combined with `OR` and `AND`, set operations inside the subquery (`... IN (SELECT b FROM y UNION SELECT b FROM z)`), extra parentheses (`EXISTS ((SELECT ...))`), and subqueries that read from CTEs defined in the outer query.

Executing a query must not modify the `sqlglot.planner.Plan` it was given. Running the same plan twice has to work, and its `expression` must be unchanged afterwards.

A correlated subquery may be re-run per outer row, but rows that share the same correlated values shouldn't each pay for a fresh execution.

Queries that already work today must keep returning the same results.
