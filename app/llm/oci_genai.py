"""Provedor principal: OCI Generative AI.

Autenticacao suportada:
  OCI_AUTH=config              -> usa ~/.oci/config (desenvolvimento local)
  OCI_AUTH=instance_principal  -> usa a identidade da propria VM (deploy em OCI)

O import do SDK e preguicoso de proposito: a aplicacao precisa subir mesmo em
uma maquina sem o pacote `oci` instalado, caindo para os provedores de reserva.
"""

from __future__ import annotations

import logging
import os

from .base import ProvedorIndisponivel

log = logging.getLogger(__name__)

MODELO_PADRAO = "meta.llama-3.3-70b-instruct"


class OciGenAI:
    nome = "oci"

    def __init__(self) -> None:
        self.compartment_id = os.getenv("OCI_COMPARTMENT_ID", "").strip()
        self.regiao = os.getenv("OCI_REGION", "sa-saopaulo-1").strip()
        self.modelo = os.getenv("OCI_GENAI_MODEL_ID", MODELO_PADRAO).strip()
        self.api_format = os.getenv("OCI_GENAI_API_FORMAT", "GENERIC").strip().upper()
        self.auth = os.getenv("OCI_AUTH", "config").strip().lower()
        self.perfil = os.getenv("OCI_CONFIG_PROFILE", "DEFAULT").strip()
        self.endpoint = os.getenv(
            "OCI_GENAI_ENDPOINT",
            f"https://inference.generativeai.{self.regiao}.oci.oraclecloud.com",
        ).strip()
        self._cliente = None

    def disponivel(self) -> bool:
        if not self.compartment_id:
            return False
        try:
            import oci  # noqa: F401
        except ImportError:
            return False
        return True

    def _obter_cliente(self):
        if self._cliente is not None:
            return self._cliente
        try:
            import oci
            from oci.generative_ai_inference import GenerativeAiInferenceClient
        except ImportError as erro:
            raise ProvedorIndisponivel("SDK `oci` nao instalado") from erro

        try:
            if self.auth == "instance_principal":
                signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
                self._cliente = GenerativeAiInferenceClient(
                    config={"region": self.regiao},
                    signer=signer,
                    service_endpoint=self.endpoint,
                    timeout=(10, 240),
                )
            else:
                config = oci.config.from_file(profile_name=self.perfil)
                self._cliente = GenerativeAiInferenceClient(
                    config=config,
                    service_endpoint=self.endpoint,
                    timeout=(10, 240),
                )
        except Exception as erro:  # credencial ausente, perfil errado, etc.
            raise ProvedorIndisponivel(f"falha ao autenticar na OCI: {erro}") from erro

        return self._cliente

    def gerar(self, sistema: str, usuario: str) -> str:
        cliente = self._obter_cliente()

        try:
            from oci.generative_ai_inference.models import (
                ChatDetails,
                CohereChatRequest,
                GenericChatRequest,
                Message,
                OnDemandServingMode,
                TextContent,
            )
        except ImportError as erro:
            raise ProvedorIndisponivel("modelos do SDK `oci` indisponiveis") from erro

        if self.api_format == "COHERE":
            pedido = CohereChatRequest(
                api_format="COHERE",
                preamble_override=sistema,
                message=usuario,
                max_tokens=1400,
                temperature=0.35,
                top_p=0.9,
            )
        else:
            pedido = GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    Message(role="SYSTEM", content=[TextContent(text=sistema)]),
                    Message(role="USER", content=[TextContent(text=usuario)]),
                ],
                max_tokens=1400,
                temperature=0.35,
                top_p=0.9,
            )

        detalhes = ChatDetails(
            compartment_id=self.compartment_id,
            serving_mode=OnDemandServingMode(model_id=self.modelo),
            chat_request=pedido,
        )

        try:
            resposta = cliente.chat(detalhes)
        except Exception as erro:
            raise ProvedorIndisponivel(f"chamada a OCI Generative AI falhou: {erro}") from erro

        texto = self._extrair_texto(resposta)
        if not texto:
            raise ProvedorIndisponivel("OCI Generative AI devolveu resposta vazia")
        return texto

    @staticmethod
    def _extrair_texto(resposta) -> str:
        dados = getattr(resposta, "data", None)
        chat = getattr(dados, "chat_response", None)
        if chat is None:
            return ""

        # Formato COHERE
        texto = getattr(chat, "text", None)
        if isinstance(texto, str) and texto.strip():
            return texto.strip()

        # Formato GENERIC
        escolhas = getattr(chat, "choices", None) or []
        partes: list[str] = []
        for escolha in escolhas:
            mensagem = getattr(escolha, "message", None)
            for bloco in getattr(mensagem, "content", None) or []:
                valor = getattr(bloco, "text", None)
                if valor:
                    partes.append(valor)
        return "\n".join(partes).strip()
