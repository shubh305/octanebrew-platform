from typing import Optional, List
from pydantic import BaseModel, Field


class CarResult(BaseModel):
    id: str
    make: str
    model: str
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    first_seen_year: Optional[int] = None
    base_price_inr: Optional[int] = None
    display_label: str


class BikeResult(BaseModel):
    id: str
    make: str
    model: str
    segment: Optional[str] = None
    fuel_type: Optional[str] = None
    first_seen_year: Optional[int] = None
    base_price_inr: Optional[int] = None
    display_label: str


class MobileResult(BaseModel):
    id: str
    make: str
    model: str
    variant: Optional[str] = None
    os: Optional[str] = None
    has_5g: Optional[bool] = None
    ram_gb: Optional[int] = None
    storage_gb: Optional[int] = None
    first_seen_year: Optional[int] = None
    base_price_inr: Optional[int] = None
    display_label: str


class BookResult(BaseModel):
    id: str
    title: str
    author: Optional[str] = None
    genre: Optional[str] = None
    publication_year: Optional[int] = None
    average_rating: Optional[float] = None
    display_label: str


class RedditDiscussion(BaseModel):
    reddit_id: str
    title: str
    url: str
    score: int
    num_comments: int
    created_utc: Optional[str] = None
    link_confidence: float


class CarSpecs(BaseModel):
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    engine_cc: Optional[int] = None
    max_power_bhp: Optional[float] = None
    max_torque_nm: Optional[float] = None
    seating_capacity: Optional[int] = None
    body_type: Optional[str] = None
    base_price_inr: Optional[int] = None
    monthly_sales: Optional[int] = None


class BikeSpecs(BaseModel):
    fuel_type: Optional[str] = None
    engine_cc: Optional[int] = None
    max_power_bhp: Optional[float] = None
    max_torque_nm: Optional[float] = None
    mileage_kmpl: Optional[float] = None
    weight_kg: Optional[int] = None
    segment: Optional[str] = None
    base_price_inr: Optional[int] = None
    on_road_price_inr: Optional[int] = None


class BookSpecs(BaseModel):
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    language: Optional[str] = None
    genre: Optional[str] = None
    average_rating: Optional[float] = None
    rating_count: Optional[int] = None


class ProductDetail(BaseModel):
    id: str
    category: str
    name: str
    brand_or_author: Optional[str] = None
    first_seen_year: Optional[int] = None
    region: str
    specs: dict = Field(default_factory=dict)
    reddit_discussions: List[RedditDiscussion] = Field(default_factory=list)


class SearchQuery(BaseModel):
    q: str = Field(..., min_length=2, description="Search query string")
    limit: int = Field(10, ge=1, le=20)
