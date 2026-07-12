from pydantic import BaseModel


class Customer(BaseModel):
    first_name: str
    last_name: str
    phone: str
    claim_status: str
    claim_id: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
