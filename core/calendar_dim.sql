CREATE OR REPLACE TABLE SUPPLYCHAINIQ_COCO.CORE.CALENDAR_DIM AS
WITH date_spine AS (
    SELECT DATEADD(DAY, seq4(), '2006-01-01'::DATE) AS calendar_date
    FROM TABLE(GENERATOR(ROWCOUNT => 4749)) -- 2006-01-01 to 2018-12-31
)
SELECT
    calendar_date                                AS CALENDAR_DATE,
    YEAR(calendar_date)                          AS YEAR_NUM,
    QUARTER(calendar_date)                       AS QUARTER_NUM,
    MONTH(calendar_date)                         AS MONTH_NUM,
    MONTHNAME(calendar_date)                     AS MONTH_NAME,
    WEEKOFYEAR(calendar_date)                    AS WEEK_OF_YEAR,
    DAYOFWEEK(calendar_date)                     AS DAY_OF_WEEK,
    DAYNAME(calendar_date)                       AS DAY_NAME,
    DATE_TRUNC('MONTH', calendar_date)::DATE     AS MONTH_START,
    DATE_TRUNC('WEEK', calendar_date)::DATE      AS WEEK_START,
    DATE_TRUNC('QUARTER', calendar_date)::DATE   AS QUARTER_START,
    DATE_TRUNC('YEAR', calendar_date)::DATE      AS YEAR_START
FROM date_spine;
