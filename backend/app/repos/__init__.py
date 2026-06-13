"""Repository layer: focused data-access modules carved out of the former
monolithic db.py. Each module owns a cohesive set of tables/queries. The
plumbing (connections, migrations, utc_now, json helpers) stays in app.db,
which these modules import as the shared core.
"""
