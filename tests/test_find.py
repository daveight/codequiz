# coding: utf-8

from tests.shared import getEmptyDeck

def test_findCards():
    deck = getEmptyDeck()
    f = deck.newFact()
    f['Front'] = u'dog'
    f['Back'] = u'cat'
    f.tags.append(u"monkey")
    deck.addFact(f)
    firstCardId = f.cards()[0].id
    f = deck.newFact()
    f['Front'] = u'goats are fun'
    f['Back'] = u'sheep'
    f.tags.append(u"sheep goat horse")
    deck.addFact(f)
    f = deck.newFact()
    f['Front'] = u'cat'
    f['Back'] = u'sheep'
    deck.addFact(f)
    catCard = f.cards()[0]
    f = deck.newFact()
    f['Front'] = u'template test'
    f['Back'] = u'foo bar'
    f.model().templates[1]['actv'] = True
    deck.addFact(f)
    latestCardIds = [c.id for c in f.cards()]
    # tag searches
    assert not deck.findCards("tag:donkey")
    assert len(deck.findCards("tag:sheep")) == 1
    assert len(deck.findCards("tag:sheep tag:goat")) == 1
    assert len(deck.findCards("tag:sheep tag:monkey")) == 0
    assert len(deck.findCards("tag:monkey")) == 1
    assert len(deck.findCards("tag:sheep -tag:monkey")) == 1
    assert len(deck.findCards("-tag:sheep")) == 4
    deck.addTags(deck.db.list("select id from cards"), "foo bar")
    assert (len(deck.findCards("tag:foo")) ==
            len(deck.findCards("tag:bar")) ==
            5)
    deck.delTags(deck.db.list("select id from cards"), "foo")
    assert len(deck.findCards("tag:foo")) == 0
    assert len(deck.findCards("tag:bar")) == 5
    # text searches
    assert len(deck.findCards("cat")) == 2
    assert len(deck.findCards("cat -dog")) == 1
    assert len(deck.findCards("cat -dog")) == 1
    assert len(deck.findCards("are goats")) == 1
    assert len(deck.findCards('"are goats"')) == 0
    assert len(deck.findCards('"goats are"')) == 1
    # card states
    c = f.cards()[0]
    c.type = 2
    assert deck.findCards("is:rev") == []
    c.flush()
    assert deck.findCards("is:rev") == [c.id]
    assert deck.findCards("is:due") == []
    c.due = 0; c.queue = 2
    c.flush()
    assert deck.findCards("is:due") == [c.id]
    assert len(deck.findCards("-is:due")) == 4
    c.queue = -1
    # ensure this card gets a later mod time
    import time; time.sleep(1)
    c.flush()
    assert deck.findCards("is:suspended") == [c.id]
    # fids
    assert deck.findCards("fid:54321") == []
    assert len(deck.findCards("fid:%d"%f.id)) == 2
    assert len(deck.findCards("fid:3,2")) == 2
    # templates
    assert len(deck.findCards("card:foo")) == 0
    assert len(deck.findCards("card:forward")) == 4
    assert len(deck.findCards("card:reverse")) == 1
    assert len(deck.findCards("card:1")) == 4
    assert len(deck.findCards("card:2")) == 1
    # fields
    assert len(deck.findCards("front:dog")) == 1
    assert len(deck.findCards("-front:dog")) == 4
    assert len(deck.findCards("front:sheep")) == 0
    assert len(deck.findCards("back:sheep")) == 2
    assert len(deck.findCards("-back:sheep")) == 3
    assert len(deck.findCards("front:")) == 5
    # ordering
    deck.conf['sortType'] = "factCrt"
    assert deck.findCards("front:")[-1] in latestCardIds
    assert deck.findCards("")[-1] in latestCardIds
    deck.conf['sortType'] = "factFld"
    assert deck.findCards("")[0] == catCard.id
    assert deck.findCards("")[-1] in latestCardIds
    deck.conf['sortType'] = "cardMod"
    assert deck.findCards("")[-1] in latestCardIds
    assert deck.findCards("")[0] == firstCardId
    deck.conf['sortBackwards'] = True
    assert deck.findCards("")[0] in latestCardIds
    # model
    assert len(deck.findCards("model:basic")) == 5
    assert len(deck.findCards("-model:basic")) == 0
    assert len(deck.findCards("-model:foo")) == 5
    # group
    assert len(deck.findCards("group:default")) == 5
    assert len(deck.findCards("-group:default")) == 0
    assert len(deck.findCards("-group:foo")) == 5
