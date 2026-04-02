# DATA_FLOW

`Dedupe_Report` + `Sorting_Suggestions` -> `main_pass2.py` -> Delta JSONL -> `PersonalBrainRuntime`.

`PersonalBrainRuntime`:
1. Source Detection über Parser Registry
2. Source Metadata + Records
3. Entity/Relation Ableitung
4. Writer-Layer für `20_index/published`
5. Daily Memory + Search Views
