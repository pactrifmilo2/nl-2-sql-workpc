ALLOWED_COLUMNS = (
    "FLIGHTNBR",
    "FROM_AIRP",
    "TO_AIRP",
    "ETD",
    "ETA",
    "VIA",
    "ATD",
    "ATA",
)

SCHEMA_CONTEXT = """
ATFM flight database (Oracle schema ATFM). Users ask in Vietnamese; SQL must use only the
column names below exactly as written (uppercase English identifiers).

Allowed columns (the complete column set — do not SELECT or filter on anything else):
- FLIGHTNBR — flight number / số hiệu chuyến bay
- FROM_AIRP — departure airport code / sân bay đi / điểm đi
- TO_AIRP — arrival airport code / sân bay đến / điểm đến
- ETD — estimated time of departure / giờ cất cánh dự kiến
- ETA — estimated time of arrival / giờ hạ cánh dự kiến
- VIA — via or intermediate airport code / điểm qua cảnh / bay qua
- ATD — actual time of departure / giờ cất cánh thực tế
- ATA — actual time of arrival / giờ hạ cánh thực tế

Tables (use schema-qualified names in SQL):
- ATFM.T_DAY_FLIGHTS — flights for the current day (scheduled times: ETD, ETA).
  Typical columns: FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA, VIA.
- ATFM.T_FINISHED_FLIGHTS — completed flights (includes actual times ATD, ATA).
  Typical columns: FLIGHTNBR, FROM_AIRP, TO_AIRP, ETD, ETA, VIA, ATD, ATA.

Table selection:
- Questions about flights today or on a given date (scheduled) -> ATFM.T_DAY_FLIGHTS.
- Questions about completed or finished flights -> ATFM.T_FINISHED_FLIGHTS.

Airport codes are stored as short codes (e.g. VVNB, VVTH, DAD). Match them exactly as in the database.

Time columns (ETD, ETA, ATD, ATA) are datetime values. Filter a calendar day with:
  column >= DATE 'YYYY-MM-DD' AND column < DATE 'YYYY-MM-DD' + 1
or TRUNC(column) = DATE 'YYYY-MM-DD'.

Vietnamese term hints (for understanding questions only — still use English column names in SQL):
- chuyến bay = flight
- trong ngày / hôm nay = T_DAY_FLIGHTS
- đã hoàn thành / đã bay xong = T_FINISHED_FLIGHTS
- từ ... đến ... = FROM_AIRP and TO_AIRP filters
- qua / đi qua = VIA filter
"""
