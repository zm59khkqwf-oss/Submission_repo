
SELECT DISTINCT sensor_id
FROM `arched-media-390414.icu_analytics.vitals_clean`
QUALIFY
  COUNTIF(body_temperature > 40) OVER (
    PARTITION BY sensor_id
    ORDER BY event_timestamp
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
  ) = 3;
