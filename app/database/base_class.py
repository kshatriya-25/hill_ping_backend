# OM VIGHNHARTAYE NAMO NAMAH :

from typing import Any
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import registry,as_declarative


mapper_registry = registry()
Base = mapper_registry.generate_base()


@as_declarative()
class Base:
    id: Any
    __name__: str

    #to generate tablename from classname
    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()