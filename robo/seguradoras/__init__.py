"""Lista de seguradoras ativas. Para incluir uma nova, crie o módulo e registre aqui."""
from .allianz import Allianz

SEGURADORAS = {
    "allianz": Allianz,
}
