import time
import json
from pydantic import BaseModel, Field
from typing import List, Optional

class EventRecord(BaseModel):
    date: str
    region: str
    source_id: str
    source_name: str
    venue: str
    title: str
    artists: List[str] = Field(default_factory=list)
    genres: List[str] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    event_url: Optional[str] = None
    source_url: str
    notes: Optional[str] = None
    confidence: float

def benchmark():
    event = EventRecord(
        date="2024-03-24",
        region="Basel",
        source_id="ra_basel",
        source_name="Resident Advisor",
        venue="Nordstern",
        title="Big Party",
        artists=["Artist A", "Artist B"],
        genres=["Techno"],
        start_time="23:00",
        source_url="https://ra.co/events/123",
        confidence=1.0
    )

    n = 10000

    # Baseline: json.loads(model.model_dump_json())
    start = time.perf_counter()
    for _ in range(n):
        _ = json.loads(event.model_dump_json())
    end = time.perf_counter()
    baseline_time = end - start
    print(f"Baseline (json.loads(model.model_dump_json())): {baseline_time:.4f}s")

    # Optimized: model.model_dump(mode='json')
    start = time.perf_counter()
    for _ in range(n):
        _ = event.model_dump(mode='json')
    end = time.perf_counter()
    optimized_time = end - start
    print(f"Optimized (model.model_dump(mode='json')): {optimized_time:.4f}s")

    if optimized_time > 0:
        improvement = (baseline_time - optimized_time) / baseline_time * 100
        print(f"Improvement: {improvement:.2f}%")

if __name__ == "__main__":
    benchmark()
