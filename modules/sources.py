import config
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class EconomicSource(BaseModel):
  name: str = Field(description="Nazwa instytucji lub źródła")
  url: str = Field(description="Oficjalny adres strony internetowej")
  description: str = Field(
      description="Krótki opis, jakie dane makroekonomiczne dostarcza"
  )


class CountrySourcesResponse(BaseModel):
  country: str
  sources: list[EconomicSource] = Field(
      description="Lista dokładnie 10 zaufanych źródeł"
  )


class PolishEconomySourceChecker:

  def __init__(self, model_name: str = config.DEFAULT_OPENAI_MODEL):
    self.llm = ChatOpenAI(
        model=model_name,
        api_key=config.OPENAI_API_KEY,
        temperature=0.1,
    )
    self.structured_llm = self.llm.with_structured_output(
        CountrySourcesResponse
    )

  def get_trusted_sources(
      self, country: str = config.DEFAULT_COUNTRY
  ) -> CountrySourcesResponse:
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "Jesteś analitykiem ekonomicznym. Twoim zadaniem jest wskazanie"
                " dokładnie 10 najbardziej zaufanych, oficjalnych i"
                " merytorycznych źródeł (instytucje rządowe, banki centralne,"
                " organizacje międzynarodowe) służących do oceny sytuacji"
                " gospodarczej wskazanego kraju."
            ),
        ),
        ("human", "Przygotuj 10 zaufanych źródeł dla kraju: {country}"),
    ])

    chain = prompt | self.structured_llm
    result = chain.invoke({"country": country})
    return result
