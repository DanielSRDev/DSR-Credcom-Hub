#costcenters_map.py
# EBM_IDS: list[str] = [
#     "191484516","192237153","192237667","192238207","192238438","192239002","192239957",
#     "192242527","192242941","192243011","192252983","192252996","192253109","192253139",
#     "192253284","192253346","192253445","192253680","192253698","192253881","192369157",
#     "192369189","192369248","192369261","192369283","192369419","192369633","192369859",
#     "192370202","192370316","192370426","194631117","192237366","192239747","192239969",
#     "192240191","192242175","192242211","192242431","192242438","192242450","192242506",
#     "192253154","192253172","192370535","201973420"
# ]

_RAW = [
    {"costCenterId":"732cf6c3-a713-4ce0-bdfb-0f3f18ce5c90","description":"Real Viver","id_cob":"194298097"},
    {"costCenterId":"1333af00-b4ee-48c1-8f43-1d146e3cc294","description":"EBM","id_cob":"201973420"},
    {"costCenterId":"e344f9d4-b284-48ca-a968-1f29e348bb04","description":"Polis Empreend","id_cob":"196223839"},
    {"costCenterId":"ca149e02-0285-4358-8e0f-22047cdd7a98","description":"Somos","id_cob":"196223841"},
    {"costCenterId":"af76811b-0c42-4819-8804-22d041d1cd70","description":"Vila Brasil","id_cob":"196224481"},
    {"costCenterId":"0cc358fb-4be8-4028-bb02-54271b2fe072","description":"JVF","id_cob":"196222276"},
    {"costCenterId":"66e1bd88-d306-4624-af5f-865d22f356a4","description":"FGR","id_cob":"194298087"},
    {"costCenterId":"f6472d7e-dad3-41b2-b799-8dd12f293757","description":"GPL","id_cob":"196222183"},
    {"costCenterId":"65bdf7fa-b576-4e8d-8b38-aefe64271689","description":"Palme","id_cob":"196223774"},
    {"costCenterId":"453e1f4a-517b-41a5-b996-b888ccd9304e","description":"Localiza Imóveis","id_cob":"196223772"},
    {"costCenterId":"7aff7e28-66a4-4afc-a186-b8e0f4683b7e","description":"LEE Empreend","id_cob":"196222153"},
    {"costCenterId":"88f5780c-5ea5-4fad-9b92-bf36ded0c419","description":"ViverBem","id_cob":"194298103"},
    {"costCenterId":"b4506fa6-8b63-4308-bd85-c90d7a3e169e","description":"Colégio Logosófico","id_cob":"196221781"},
    {"costCenterId":"3f449bf5-9e18-4e0c-bf94-d521ee4f123b","description":"Fortes","id_cob":"196222094"},
    {"costCenterId":"85242d04-c8a9-4780-ad64-f03a614f4398","description":"AM3 Imobiliária","id_cob":"194298055"},
    {"costCenterId":"85b27254-cbd7-4a91-b133-f1b9baa96323","description":"Cooperativa - Sicoob","id_cob":"196704575"},
    {"costCenterId":"3d78c359-0993-408d-bdf0-f23c47196dc7","description":"Valle Prime","id_cob":"196224085"},
    {"costCenterId":"8d406299-6a0e-4e24-8db4-d01ea71e6249","description":"HB","id_cob":"198948068"},
    {"costCenterId":"d0a0afba-7eef-4d11-bda3-e39988514c3c","description":"Mais VGV","id_cob":"197677345"},
    {"costCenterId":"b4fe2577-bc0a-401c-b3d5-6f4fc42aa033","description":"El Shadai","id_cob":"205199780"},
    {"costCenterId":"6e952f70-8516-4ceb-9a66-7a78db4e4735","description":"Adão Imóveis","id_cob":"207870329"},
    {"costCenterId":"27c09c93-2a7b-4ada-a40d-6135a7d4b227","description":"Enec Engenharia","id_cob":"207867083"},
]

COSTCENTER_BY_IDCOB = {
    str(it["id_cob"]): it["costCenterId"]
    for it in _RAW
    if it.get("id_cob")
}

def get_costcenter_by_idcob(id_cob_ou_sigla) -> str | None:
    """
    Normaliza o id (str/int/com espaços) e retorna o costCenterId.
    """
    if id_cob_ou_sigla is None:
        return None
    key = str(id_cob_ou_sigla).strip()
    return COSTCENTER_BY_IDCOB.get(key)
