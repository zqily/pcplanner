from datetime import datetime
from typing import List, Optional
from sqlalchemy import Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[List["Item"]] = relationship("Item", back_populates="profile", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Profile(name='{self.name}')>"

class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID Hex
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # 'components' or 'peripherals'
    
    name: Mapped[str] = mapped_column(String, nullable=False)
    link: Mapped[str] = mapped_column(String, default="")
    specs: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String, default="")
    
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    current_price: Mapped[int] = mapped_column(Integer, default=0)
    previous_price: Mapped[int] = mapped_column(Integer, default=0)
    
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    profile: Mapped["Profile"] = relationship("Profile", back_populates="items")
    price_history: Mapped[List["PriceHistory"]] = relationship("PriceHistory", back_populates="item", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """Converts model to a dictionary compatible with the UI."""
        return {
            "id": self.id,
            "category": self.category,
            "name": self.name,
            "link": self.link,
            "specs": self.specs,
            "image_url": self.image_url,
            "quantity": self.quantity,
            "price": self.current_price,
            "previous_price": self.previous_price,
            "order_index": self.order_index
        }

class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), index=True)
    date: Mapped[str] = mapped_column(String, nullable=False)  # ISO Format YYYY-MM-DD
    price: Mapped[int] = mapped_column(Integer, nullable=False)

    item: Mapped["Item"] = relationship("Item", back_populates="price_history")

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "price": self.price
        }