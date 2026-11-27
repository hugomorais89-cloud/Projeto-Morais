"""Lista de seguradoras ativas. Para incluir uma nova, crie o módulo e registre aqui."""
from .akad import Akad
from .allianz import Allianz
from .bradesco import Bradesco
from .ezze import Ezze
from .hdi import Hdi
from .mapfre import Mapfre
from .novo import Novo
from .suhai import Suhai
from .tokio import TokioMarine
from .yelum import Yelum
from .zurich import Zurich

SEGURADORAS = {
    "allianz": Allianz,
    "tokio": TokioMarine,
    "ezze": Ezze,
    "hdi": Hdi,
    "yelum": Yelum,
    "mapfre": Mapfre,
    "suhai": Suhai,
    "zurich": Zurich,
    "bradesco": Bradesco,
    "novo": Novo,
    "akad": Akad,
}
