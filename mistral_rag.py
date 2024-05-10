import bs4
from langchain_community.llms import Ollama
from langchain_community.embeddings import OllamaEmbeddings
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_chroma import Chroma
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders.merge import MergedDataLoader
from langchain_community.document_loaders import PyPDFDirectoryLoader
import logging

logging.getLogger().setLevel(logging.ERROR)

llm = Ollama(model="mistralfr")
embeddings = OllamaEmbeddings(model="mistralfr")


# Open the file and read the URLs
with open('URLlinks.txt', 'r') as file:
    webURLs = [line.strip() for line in file.readlines()]

# Construct retriever
loader_web = WebBaseLoader(
    web_paths=tuple(webURLs),
    bs_kwargs=dict(
        parse_only=bs4.SoupStrainer(
            class_=("entry-header", "entry-content")
        )
    ),
)

loader_pdf = PyPDFDirectoryLoader("pdf_data/")

docsPDF = loader_pdf.load()
docsWEB = loader_web.load()

merged_loader = MergedDataLoader(loaders=[loader_web, loader_pdf])
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
docs = merged_loader.load_and_split(text_splitter)

# Store the database on disk (only needed once) then comment it
vectorstore = Chroma.from_documents(documents=docs, embedding=embeddings, persist_directory="/media/mathieu/Data_Storage/Programmation/DataBase/chroma_db")
# Load from disk instead
#vectorstore = Chroma(persist_directory="/media/mathieu/Data_Storage/Programmation/DataBase/chroma_db", embedding=embeddings)

retriever = vectorstore.as_retriever()

### Contextualize question ###
contextualize_q_system_prompt = """À partir de l'historique de discussion et de la dernière question de l'utilisateur, qui pourrait faire référence au contexte de l'historique de discussion, formulez une question autonome qui peut être comprise sans l'historique de la discussion. NE répondez PAS à la question, reformulez-la simplement si nécessaire, sinon renvoyez-la telle quelle."""
contextualize_q_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)
history_aware_retriever = create_history_aware_retriever(
    llm, retriever, contextualize_q_prompt
)


### Answer question ###
qa_system_prompt = """Vous êtes un assistant pour les tâches de question-réponse. Utilisez les éléments de contexte suivants pour répondre à la question. Si vous ne connaissez pas la réponse, dites simplement que vous ne savez pas. Utilisez un maximum de trois phrases et gardez la réponse concise.\
{context}"""

qa_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", qa_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)
question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)

rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)


### Statefully manage chat history ###
store = {}


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


conversational_rag_chain = RunnableWithMessageHistory(
    rag_chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
    output_messages_key="answer",
)

while(True):
    print("\nPose une question ou écris 'exit' pour arrêter.\n")
    question = input()
    if question == "exit":
        break

    answer = conversational_rag_chain.invoke(
        {"input": question},
        config={
            "configurable": {"session_id": "abc123"}
        },  # constructs a key "abc123" in `store`.
    )

    print(answer["answer"])

    for i, document in enumerate(answer["context"]):
        print("Source "+ str(i+1) + " : " + document.metadata["source"])

# ex : What is Task Decomposition?