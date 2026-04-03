import re

# Update main_pass2.py to use `exclusions` in `process_sources`
with open('bummdidumm_os_v5_final_release/main_pass2.py', 'r') as f:
    main_pass2_content = f.read()

main_pass2_content = main_pass2_content.replace(
    'runtime.process_sources(\n            _build_personal_brain_sources(records_to_index, drive_service, ENABLE_SHARED_DRIVES)\n        )',
    'runtime.process_sources(\n            _build_personal_brain_sources(records_to_index, drive_service, ENABLE_SHARED_DRIVES),\n            exclusions\n        )'
)

with open('bummdidumm_os_v5_final_release/main_pass2.py', 'w') as f:
    f.write(main_pass2_content)
