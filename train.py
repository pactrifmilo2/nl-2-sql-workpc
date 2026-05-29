from nl_2_sql_vanna_oracle_pc.logging_config import configure_logging
from nl_2_sql_vanna_oracle_pc.settings import settings
from nl_2_sql_vanna_oracle_pc.training import main

configure_logging(settings)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
