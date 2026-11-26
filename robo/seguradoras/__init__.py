"""Lista de seguradoras ativas. Para incluir uma nova, crie o módulo e registre aqui."""
from .allianz import Allianz
from .ezze import Ezze
from .hdi import Hdi
from .tokio import TokioMarine
from .yelum import Yelum

SEGURADORAS = {
    "allianz": Allianz,
    "tokio": TokioMarine,
    "ezze": Ezze,
    "hdi": Hdi,
    "yelum": Yelum,
}
