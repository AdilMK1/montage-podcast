"""Registre des types de tâches : {nom: gestionnaire(ctx)}."""
from app.services.casting import pre_analyse
from app.services.taches_analyse import analyse, son
from app.services.taches_episode import coupes, essai, export, livraison, montage
from app.services.taches_ia import ia_passages, ia_shorts
from app.services.taches_rendu import apercus, proxys, shorts

TYPES = {"pre_analyse": pre_analyse, "analyse": analyse, "son": son, "ia_shorts": ia_shorts, "ia_passages": ia_passages,
         "proxys": proxys, "apercus": apercus, "shorts": shorts, "montage": montage, "essai": essai,
         "export": export, "coupes": coupes, "livraison": livraison}
