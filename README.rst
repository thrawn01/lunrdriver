Lunr driver for Cinder Volumes
============================

Using
-----

The following config items need to be configured in `cinder.conf`::

    volume_driver=lunrdriver.driver.LunrDriver
    lunr_api_endpoint=http://localhost:8080/v1.0
    no_snapshot_gb_quota=True
    quota_snapshots=-1
