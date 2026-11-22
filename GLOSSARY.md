# Docent

A chat that answers questions only from documents its users upload, citing the exact passages it used, and declining when the documents don't contain the answer.

## Content

**Library**:
Everything a User can reach in Docent: their Collections and the Documents in them.
_Avoid_: Workspace, dashboard, home

**Collection**:
A named set of Documents with its own Members; the unit of sharing and of asking.
_Avoid_: Folder, workspace, space, knowledge base

**Personal Collection**:
The private Collection every User has from sign-up.
_Avoid_: My docs, private space

**Public Collection**:
A Collection that anyone with its link (or its Widget) can ask, without signing in, until an optional expiry.
_Avoid_: Shared link collection, open collection

**Demo Collection**:
The Collection of openly licensed Documents that every User can ask, read-only, and that the Eval Set is built on. It has no Owner: maintainers change it by editing its source list and seeding it again. It becomes a Public Collection, open to Visitors, with M4.
_Avoid_: Sample data, showcase

**Widget**:
The embeddable chat that answers from one Public Collection on any website.
_Avoid_: Embed, plugin, chatbot

**API Key**:
A revocable, ask-only credential that belongs to one Collection and is created by its Owner.
_Avoid_: Token, secret, access key

**Document**:
One uploaded file or web page, belonging to exactly one Collection.
_Avoid_: File, source, doc (in code and UI copy)

**Replace**:
The explicit action of giving an existing Document new content; any other upload creates a new Document.
_Avoid_: Update, re-upload, new version

**Move**:
Transferring a Document from one Collection to another, keeping its history; requires Editor or Owner Role in both.
_Avoid_: Copy, re-upload

**Effective Date**:
The date a Document's content applies from, set by the uploader and defaulting to the upload date; used to order Documents that disagree.
_Avoid_: Upload date, document date

## People

**User**:
A person with a signed-in account.
_Avoid_: Account, customer

**Member**:
A User's place in a Collection, with exactly one Role.
_Avoid_: Collaborator, participant

**Invite**:
An Owner's offer of a Role in a Collection to an email address; signing in with that address makes its User a Member. Docent sends no email: the Owner passes on its link.
_Avoid_: Invitation email, share request

**Role**:
What a Member may do in a Collection: Owner, Editor, or Viewer.
_Avoid_: Permission level, access level

**Owner**:
The single Member who controls a Collection's membership, publishing, and deletion; transferable.
_Avoid_: Admin, creator

**Editor**:
A Member who can add, Replace, and delete Documents, and ask.
_Avoid_: Contributor, uploader

**Viewer**:
A Member who can only ask.
_Avoid_: Reader, guest

**Visitor**:
Someone asking a Public Collection without signing in; has no saved history.
_Avoid_: Anonymous user, guest

## Answers

**Conversation**:
A sequence of questions and answers by one User; it is saved automatically.
_Avoid_: Chat, thread, session

**Scope**:
The Collections a question is answered from; it can change during a Conversation, and every answer records the Scope it used.
_Avoid_: Context, filter, selection

**Citation**:
A numbered reference in an answer to the exact passage that supports a claim; it always shows the passage as it was when the answer was given.
_Avoid_: Source, reference, footnote

**Claim**:
A sentence or list item of an answer that cites at least one passage. A Claim whose Citations can't be checked against their passages is removed from the answer, and the answer says so.
_Avoid_: Statement, assertion

**Decline**:
An answer stating the Documents in Scope don't contain the answer, offered with the closest passages instead of a guess.
_Avoid_: Fallback, refusal, no-answer

**Answer Log**:
The record of every answer given, including Visitors' answers, kept for 90 days for quality review and evaluation (entries promoted to the Eval Set are kept).
_Avoid_: Trace, history, audit log

**Eval Set**:
The single, human-reviewed list of questions about the Demo Collection, each with its expected passages or marked unanswerable, that Docent's answer quality is measured against.
_Avoid_: Test set, benchmark, golden set
