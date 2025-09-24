from typing import List, TypedDict


class CandleData(TypedDict):
    o: List[float]
    h: List[float]
    l: List[float]
    c: List[float]
    v: List[float]
    t: List[float]


class CandleDataListItem(TypedDict):
    symbol: str
    data: CandleData


class CandleDataList(TypedDict):
    failed: List[str]
    results: List[CandleDataListItem]
