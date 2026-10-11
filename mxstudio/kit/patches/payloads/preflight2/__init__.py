"""MODULEX_MAG P-PREFLIGHT2 payload (OM printing): append mx_preflight2 checks to preflight.run().

Installed by the Magazine Studio Integration Kit. Active only when MODULEX_MAG_PREFLIGHT2=1
(read when app/printing/preflight.py is imported). Never writes print state: print_service.py
stays the only writer of print_jobs / print_job_events / orders.fulfilment_status.
Revert with: python -m mxstudio.kit revert --patch P-PREFLIGHT2
"""
