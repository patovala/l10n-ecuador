from datetime import datetime
import json
from unittest.mock import create_autospec, patch, MagicMock

from zeep import Client
from zeep.transports import Transport

from odoo.addons.l10n_ec_account_edi.models.account_edi_format import (
    AccountEdiFormat,
)

mock_type_factory = MagicMock()
ws_url = "https://any.fake.url"
transport = Transport(timeout=30)
wsClient = MagicMock()
wsClient.type_factory.return_value = mock_type_factory
factory = wsClient.type_factory("ns0")
autorizadoObj = MagicMock()
autorizadoObj.estado = "RECIBIDA"
autorizadoObj.comprobantes = ([{"comprobante": MagicMock}],)
autorizadoObj.autorizaciones = {
    "autorizacion": [
        MagicMock(
            estado="AUTORIZADO",
            numeroAutorizacion="DUMMY_ACCESS_KEY2",
            fechaAutorizacion=datetime.now(),
            ambiente="PRUEBAS",
            comprobante="",
            mensajes={"mensaje": []},
        )
    ]
}

mock_type_factory.respuestaSolicitud.return_value = autorizadoObj


sri_message_date = factory.mensaje(
    identificador="65",
    informacionAdicional="La fecha de emisión está fuera del rango de tolerancia "
    "[129600 minutos], o es mayor a la fecha del servidor",
    mensaje="FECHA EMISIÓN EXTEMPORANEA",
    tipo="ERROR",
)

# validation_sri_response = factory.respuestaSolicitud(
# validation_sri_response = {
#     "comprobantes": [
#         MagicMock(
#             return_value={
#                 "estado": "RECIBIDA",
#                 "comprobantes": [
#                     {
#                         "comprobante": [
#                             MagicMock(
#                                 return_value={
#                                     "claveAcceso": "DUMMY_ACCESS_KEY",
#                                     "mensajes": {"mensaje": []},
#                                 }
#                             )
#                         ]
#                     }
#                 ],
#             }
#         )
#     ]
# }

validation_sri_response = json.loads(
    """
    {
      "estado": "RECIBIDA",
      "comprobantes": {
        "comprobante": {
            "claveAcceso": "DUMMY_ACCESS_KEY8",
            "mensajes": {
              "mensaje": [
                {
                  "tipo": "NADA",
                  "identificador": "xxx",
                  "mensaje": "odoo is good",
                  "informacionAdicional": "nada"
                }
              ]
            }
          }
      }
    }
"""
)

validation_sri_response_returned = factory.respuestaSolicitud(
    estado="DEVUELTA",
    comprobantes=[
        {
            "comprobante": [
                factory.comprobante(
                    claveAcceso="DUMMY_ACCESS_KEY3",
                    mensajes={"mensaje": [sri_message_date]},
                )
            ]
        }
    ],
)

auth_sri_response = factory.respuestaComprobante(
    claveAccesoConsultada="DUMMY_ACCESS_KEY9",
    numeroComprobantes=1,
    autorizaciones={
        "autorizacion": [
            factory.autorizacion(
                estado="AUTORIZADO",
                numeroAutorizacion="DUMMY_ACCESS_KEY9",
                fechaAutorizacion=datetime.now(),
                ambiente="PRUEBAS",
                comprobante="",
                mensajes={"mensaje": []},
            )
        ]
    },
)


def _mock_create_client(validation_response, auth_response):
    mock_client = create_autospec(Client)
    mock_client.service.validarComprobante.return_value = validation_response
    mock_client.service.autorizacionComprobante.return_value = auth_response
    return mock_client


def patch_service_sri(*args, **kwargs):
    """
    Change the Zeep Client to Mock
    so as not to consume SRI's webservices validarComprobante.

    Example usage
    - use default response(OK)

    @patch_service_sri
    def test_my_test(self)
        Your code

    - change default response(Returned)
    @patch_service_sri(validation_response=CustomResponse)
    def test_my_test(self)
        Your code

    :param validation_response: the response expected,
        if is None then use 'validation_sri_response'
    """

    def wrapper(func):
        def patched(self, *func_args, **func_kwargs):
            validation_response = kwargs.get("validation_response", validation_sri_response)
            auth_response = kwargs.get("auth_response", autorizadoObj)
            mock_client = _mock_create_client(validation_response, auth_response)
            with patch.object(AccountEdiFormat, "_l10n_ec_get_edi_ws_client", return_value=mock_client):
                return func(self, *func_args, **func_kwargs)

        return patched

    # Si el decorador se usa con un argumento (callable), devuelve el decorador aplicado
    if args and callable(args[0]):
        return wrapper(args[0])
    return wrapper
