# Citations keep the passage text they were based on

When a Document is Replaced, the text of its old chunks is retained (their embeddings are not) so that every past Citation still shows the exact passage the answer used, labelled as replaced. Re-pointing Citations to the new version would silently make old answers unverifiable or contradictory. The cost is storing superseded chunk text indefinitely; it is excluded from retrieval and purged only when the Document itself is deleted, at which point Citations show the source as removed.
