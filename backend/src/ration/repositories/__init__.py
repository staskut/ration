"""Database access, and the mapping between rows and domain types.

This layer is the only place that knows SQLAlchemy exists. Repositories read
rows and return frozen domain objects; nothing with an ORM identity crosses
outwards. Business rules live in `ration.domain` and are not repeated here.
"""
