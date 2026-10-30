-- Rows to fix
-- Tab: Sync Health · Visualization: Table
-- The same message is written next to the row in the sheet's sync_status column.

SELECT source        AS "Tab",
       sheet_row     AS "Row",
       row_key       AS "ID",
       error_type    AS "Error",
       message       AS "What to fix",
       first_seen_at AS "Since"
FROM   sync_errors
WHERE  resolved_at IS NULL
ORDER  BY source, sheet_row;
