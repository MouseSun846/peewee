from peewee import *

from .base import get_in_memory_db
from .base import requires_models
from .base import ModelTestCase
from .base import TestModel


class Person(TestModel):
    name = TextField()


class Relationship(TestModel):
    from_person = ForeignKeyField(Person, backref='relationships')
    to_person = ForeignKeyField(Person, backref='related_to')


class Note(TestModel):
    person = ForeignKeyField(Person, backref='notes')
    content = TextField()


class NoteItem(TestModel):
    note = ForeignKeyField(Note, backref='items')
    content = TextField()


class Like(TestModel):
    person = ForeignKeyField(Person, backref='likes')
    note = ForeignKeyField(Note, backref='likes')


class Flag(TestModel):
    note = ForeignKeyField(Note, backref='flags')
    is_spam = BooleanField()


class Category(TestModel):
    name = TextField()
    parent = ForeignKeyField('self', backref='children', null=True)


class Package(TestModel):
    barcode = TextField(unique=True)


class PackageItem(TestModel):
    name = TextField()
    package = ForeignKeyField(Package, backref='items', field=Package.barcode)


class TestPrefetch(ModelTestCase):
    database = get_in_memory_db()
    requires = [Person, Note, NoteItem, Like, Flag]

    def create_test_data(self):
        data = {
            'huey': (
                ('meow', ('meow-1', 'meow-2', 'meow-3')),
                ('purr', ()),
                ('hiss', ('hiss-1', 'hiss-2'))),
            'mickey': (
                ('woof', ()),
                ('bark', ('bark-1', 'bark-2'))),
            'zaizee': (),
        }
        for name, notes in sorted(data.items()):
            person = Person.create(name=name)
            for note, items in notes:
                note = Note.create(person=person, content=note)
                for item in items:
                    NoteItem.create(note=note, content=item)

        Flag.create(note=Note.get(Note.content == 'purr'), is_spam=True)
        Flag.create(note=Note.get(Note.content == 'woof'), is_spam=True)

        Like.create(note=Note.get(Note.content == 'meow'),
                    person=Person.get(Person.name == 'mickey'))
        Like.create(note=Note.get(Note.content == 'woof'),
                    person=Person.get(Person.name == 'huey'))

    def setUp(self):
        super(TestPrefetch, self).setUp()
        self.create_test_data()

    def accumulate_results(self, query, sort_items=False):
        accum = []
        for person in query:
            notes = []
            for note in person.notes:
                items = []
                for item in note.items:
                    items.append(item.content)
                if sort_items:
                    items.sort()
                notes.append((note.content, items))
            if sort_items:
                notes.sort()
            accum.append((person.name, notes))
        return accum

    def test_prefetch_simple(self):
        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(3):
                people = Person.select().order_by(Person.name)
                query = people.prefetch(Note, NoteItem, prefetch_type=pt)
                accum = self.accumulate_results(query, sort_items=True)

            self.assertEqual(accum, [
                ('huey', [
                    ('hiss', ['hiss-1', 'hiss-2']),
                    ('meow', ['meow-1', 'meow-2', 'meow-3']),
                    ('purr', [])]),
                ('mickey', [
                    ('bark', ['bark-1', 'bark-2']),
                    ('woof', [])]),
                ('zaizee', []),
            ])

    def test_prefetch_filter(self):
        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(3):
                people = Person.select().order_by(Person.name)
                notes = (Note
                         .select()
                         .where(Note.content.not_in(('hiss', 'meow', 'woof')))
                         .order_by(Note.content.desc()))
                items = NoteItem.select().where(
                    ~NoteItem.content.endswith('-2'))
                query = prefetch(people, notes, items, prefetch_type=pt)
                self.assertEqual(self.accumulate_results(query), [
                    ('huey', [('purr', [])]),
                    ('mickey', [('bark', ['bark-1'])]),
                    ('zaizee', []),
                ])

    def test_prefetch_reverse(self):
        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(2):
                people = Person.select().order_by(Person.name)
                notes = Note.select().order_by(Note.content)
                query = prefetch(notes, people, prefetch_type=pt)
                accum = [(note.content, note.person.name) for note in query]
                self.assertEqual(accum, [
                    ('bark', 'mickey'),
                    ('hiss', 'huey'),
                    ('meow', 'huey'),
                    ('purr', 'huey'),
                    ('woof', 'mickey')])

    def test_prefetch_reverse_with_parent_join(self):
        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(2):
                notes = (Note
                         .select(Note, Person)
                         .join(Person)
                         .order_by(Note.content))
                items = NoteItem.select().order_by(NoteItem.content.desc())
                query = prefetch(notes, items, prefetch_type=pt)
                accum = [(note.person.name,
                          note.content,
                          [item.content for item in note.items])
                         for note in query]
                self.assertEqual(accum, [
                    ('mickey', 'bark', ['bark-2', 'bark-1']),
                    ('huey', 'hiss', ['hiss-2', 'hiss-1']),
                    ('huey', 'meow', ['meow-3', 'meow-2', 'meow-1']),
                    ('huey', 'purr', []),
                    ('mickey', 'woof', []),
                ])

    def test_prefetch_multi_depth(self):
        for pt in PREFETCH_TYPE.values():
            people = Person.select().order_by(Person.name)
            notes = Note.select().order_by(Note.content)
            items = NoteItem.select().order_by(NoteItem.content)
            flags = Flag.select().order_by(Flag.id)

            LikePerson = Person.alias('lp')
            likes = (Like
                     .select(Like, LikePerson.name)
                     .join(LikePerson, on=(Like.person == LikePerson.id)))

            # Five queries:
            # - person (outermost query)
            # - notes for people
            # - items for notes
            # - flags for notes
            # - likes for notes (includes join to person)
            with self.assertQueryCount(5):
                query = prefetch(people, notes, items, flags, likes,
                                 prefetch_type=pt)
                accum = []
                for person in query:
                    notes = []
                    for note in person.notes:
                        items = [item.content for item in note.items]
                        likes = [like.person.name for like in note.likes]
                        flags = [flag.is_spam for flag in note.flags]
                        notes.append((note.content, items, likes, flags))
                    accum.append((person.name, notes))

            self.assertEqual(accum, [
                ('huey', [
                    ('hiss', ['hiss-1', 'hiss-2'], [], []),
                    ('meow', ['meow-1', 'meow-2', 'meow-3'], ['mickey'], []),
                    ('purr', [], [], [True])]),
                ('mickey', [
                    ('bark', ['bark-1', 'bark-2'], [], []),
                    ('woof', [], ['huey'], [True])]),
                (u'zaizee', []),
            ])

    def test_prefetch_multi_depth_no_join(self):
        for pt in PREFETCH_TYPE.values():
            LikePerson = Person.alias()
            people = Person.select().order_by(Person.name)
            notes = Note.select().order_by(Note.content)
            items = NoteItem.select().order_by(NoteItem.content)
            flags = Flag.select().order_by(Flag.id)

            with self.assertQueryCount(6):
                query = prefetch(people, notes, items, flags, Like, LikePerson,
                                 prefetch_type=pt)
                accum = []
                for person in query:
                    notes = []
                    for note in person.notes:
                        items = [item.content for item in note.items]
                        likes = [like.person.name for like in note.likes]
                        flags = [flag.is_spam for flag in note.flags]
                        notes.append((note.content, items, likes, flags))
                    accum.append((person.name, notes))

            self.assertEqual(accum, [
                ('huey', [
                    ('hiss', ['hiss-1', 'hiss-2'], [], []),
                    ('meow', ['meow-1', 'meow-2', 'meow-3'], ['mickey'], []),
                    ('purr', [], [], [True])]),
                ('mickey', [
                    ('bark', ['bark-1', 'bark-2'], [], []),
                    ('woof', [], ['huey'], [True])]),
                (u'zaizee', []),
            ])

    def test_prefetch_with_group_by(self):
        for pt in PREFETCH_TYPE.values():
            people = (Person
                      .select(Person, fn.COUNT(Note.id).alias('note_count'))
                      .join(Note, JOIN.LEFT_OUTER)
                      .group_by(Person)
                      .order_by(Person.name))
            notes = Note.select().order_by(Note.content)
            items = NoteItem.select().order_by(NoteItem.content)
            with self.assertQueryCount(3):
                query = prefetch(people, notes, items, prefetch_type=pt)
                self.assertEqual(self.accumulate_results(query), [
                    ('huey', [
                        ('hiss', ['hiss-1', 'hiss-2']),
                        ('meow', ['meow-1', 'meow-2', 'meow-3']),
                        ('purr', [])]),
                    ('mickey', [
                        ('bark', ['bark-1', 'bark-2']),
                        ('woof', [])]),
                    ('zaizee', []),
                ])

                huey, mickey, zaizee = query
                self.assertEqual(huey.note_count, 3)
                self.assertEqual(mickey.note_count, 2)
                self.assertEqual(zaizee.note_count, 0)

    @requires_models(Category)
    def test_prefetch_self_join(self):
        def cc(name, parent=None):
            return Category.create(name=name, parent=parent)
        root = cc('root')
        p1 = cc('p1', root)
        p2 = cc('p2', root)
        for p in (p1, p2):
            for i in range(2):
                cc('%s-%s' % (p.name, i + 1), p)

        for pt in PREFETCH_TYPE.values():
            Child = Category.alias('child')
            with self.assertQueryCount(2):
                query = prefetch(Category.select().order_by(Category.id),
                                 Child, prefetch_type=pt)
                names_and_children = [
                    (cat.name, [child.name for child in cat.children])
                    for cat in query]

            self.assertEqual(names_and_children, [
                ('root', ['p1', 'p2']),
                ('p1', ['p1-1', 'p1-2']),
                ('p2', ['p2-1', 'p2-2']),
                ('p1-1', []),
                ('p1-2', []),
                ('p2-1', []),
                ('p2-2', []),
            ])

    @requires_models(Category)
    def test_prefetch_adjacency_list(self):
        def cc(name, parent=None):
            return Category.create(name=name, parent=parent)

        tree = ('root', (
            ('n1', (
                ('c11', ()),
                ('c12', ()))),
            ('n2', (
                ('c21', ()),
                ('c22', (
                    ('g221', ()),
                    ('g222', ()))),
                ('c23', ()),
                ('c24', (
                    ('g241', ()),
                    ('g242', ()),
                    ('g243', ())))))))
        stack = [(None, tree)]
        while stack:
            parent, (name, children) = stack.pop()
            node = cc(name, parent)
            for child_tree in children:
                stack.insert(0, (node, child_tree))

        for pt in PREFETCH_TYPE.values():
            C = Category.alias('c')
            G = Category.alias('g')
            GG = Category.alias('gg')
            GGG = Category.alias('ggg')
            query = Category.select().where(Category.name == 'root')
            with self.assertQueryCount(5):
                pf = prefetch(query, C, (G, C), (GG, G), (GGG, GG),
                              prefetch_type=pt)
                def gather(c):
                    children = sorted([gather(ch) for ch in c.children])
                    return (c.name, tuple(children))
                nodes = list(pf)
                self.assertEqual(len(nodes), 1)
                pf_tree = gather(nodes[0])

            self.assertEqual(tree, pf_tree)

    def test_prefetch_specific_model(self):
        # Person -> Note
        #        -> Like (has fks to both person and note)
        Like.create(note=Note.get(Note.content == 'woof'),
                    person=Person.get(Person.name == 'zaizee'))
        NoteAlias = Note.alias('na')

        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(3):
                people = Person.select().order_by(Person.name)
                notes = Note.select().order_by(Note.content)
                likes = (Like
                         .select(Like, NoteAlias.content)
                         .join(NoteAlias, on=(Like.note == NoteAlias.id))
                         .order_by(NoteAlias.content))
                query = prefetch(people, notes, (likes, Person),
                                 prefetch_type=pt)
                accum = []
                for person in query:
                    likes = []
                    notes = []
                    for note in person.notes:
                        notes.append(note.content)
                    for like in person.likes:
                        likes.append(like.note.content)
                    accum.append((person.name, notes, likes))

            self.assertEqual(accum, [
                ('huey', ['hiss', 'meow', 'purr'], ['woof']),
                ('mickey', ['bark', 'woof'], ['meow']),
                ('zaizee', [], ['woof']),
            ])

    @requires_models(Relationship)
    def test_multiple_foreign_keys(self):
        self.database.pragma('foreign_keys', 0)
        Person.delete().execute()
        c, h, z = [Person.create(name=name) for name in
                                 ('charlie', 'huey', 'zaizee')]
        RC = lambda f, t: Relationship.create(from_person=f, to_person=t)
        r1 = RC(c, h)
        r2 = RC(c, z)
        r3 = RC(h, c)
        r4 = RC(z, c)

        def assertRelationships(attr, values):
            self.assertEqual(len(attr),len(values))
            for relationship, value in zip(attr, values):
                self.assertEqual(relationship.__data__, value)

        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(2):
                people = Person.select().order_by(Person.name)
                relationships = Relationship.select().order_by(Relationship.id)
                query = prefetch(people, relationships, prefetch_type=pt)
                cp, hp, zp = list(query)

                assertRelationships(cp.relationships, [
                    {'id': r1.id, 'from_person': c.id, 'to_person': h.id},
                    {'id': r2.id, 'from_person': c.id, 'to_person': z.id}])
                assertRelationships(cp.related_to, [
                    {'id': r3.id, 'from_person': h.id, 'to_person': c.id},
                    {'id': r4.id, 'from_person': z.id, 'to_person': c.id}])

                assertRelationships(hp.relationships, [
                    {'id': r3.id, 'from_person': h.id, 'to_person': c.id}])
                assertRelationships(hp.related_to, [
                    {'id': r1.id, 'from_person': c.id, 'to_person': h.id}])

                assertRelationships(zp.relationships, [
                    {'id': r4.id, 'from_person': z.id, 'to_person': c.id}])
                assertRelationships(zp.related_to, [
                    {'id': r2.id, 'from_person': c.id, 'to_person': z.id}])

            with self.assertQueryCount(2):
                query = prefetch(relationships, people, prefetch_type=pt)
                accum = []
                for row in query:
                    accum.append((row.from_person.name, row.to_person.name))
                self.assertEqual(accum, [
                    ('charlie', 'huey'),
                    ('charlie', 'zaizee'),
                    ('huey', 'charlie'),
                    ('zaizee', 'charlie')])

        m = Person.create(name='mickey')
        RC(h, m)

        def assertNames(p, ns):
            self.assertEqual([r.to_person.name for r in p.relationships], ns)

        # Use prefetch to go Person -> Relationship <- Person (PA).
        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(3):
                people = (Person
                          .select()
                          .where(Person.name != 'mickey')
                          .order_by(Person.name))
                relationships = Relationship.select().order_by(Relationship.id)
                PA = Person.alias()
                query = prefetch(people, relationships, PA, prefetch_type=pt)
                cp, hp, zp = list(query)
                assertNames(cp, ['huey', 'zaizee'])
                assertNames(hp, ['charlie', 'mickey'])
                assertNames(zp, ['charlie'])

            # User prefetch to go Person -> Relationship+Person (PA).
            with self.assertQueryCount(2):
                people = (Person
                          .select()
                          .where(Person.name != 'mickey')
                          .order_by(Person.name))
                rels = (Relationship
                        .select(Relationship, PA)
                        .join(PA, on=(Relationship.to_person == PA.id))
                        .order_by(Relationship.id))
                query = prefetch(people, rels, prefetch_type=pt)
                cp, hp, zp = list(query)
                assertNames(cp, ['huey', 'zaizee'])
                assertNames(hp, ['charlie', 'mickey'])
                assertNames(zp, ['charlie'])

    def test_prefetch_through_manytomany(self):
        Like.create(note=Note.get(Note.content == 'meow'),
                    person=Person.get(Person.name == 'zaizee'))
        Like.create(note=Note.get(Note.content == 'woof'),
                    person=Person.get(Person.name == 'zaizee'))

        for pt in PREFETCH_TYPE.values():
            with self.assertQueryCount(3):
                people = Person.select().order_by(Person.name)
                notes = Note.select().order_by(Note.content)
                likes = Like.select().order_by(Like.id)
                query = prefetch(people, likes, notes, prefetch_type=pt)
                accum = []
                for person in query:
                    liked_notes = []
                    for like in person.likes:
                        liked_notes.append(like.note.content)
                    accum.append((person.name, liked_notes))

            self.assertEqual(accum, [
                ('huey', ['woof']),
                ('mickey', ['meow']),
                ('zaizee', ['meow', 'woof']),
            ])

    @requires_models(Package, PackageItem)
    def test_prefetch_non_pk_fk(self):
        data = (
            ('101', ('a', 'b')),
            ('102', ('a', 'b')),
            ('103', ()),
            ('104', ('a', 'b', 'c', 'd', 'e')),
        )
        for barcode, items in data:
            Package.create(barcode=barcode)
            for item in items:
                PackageItem.create(package=barcode, name=item)

        for pt in PREFETCH_TYPE.values():
            packages = Package.select().order_by(Package.barcode)
            items = PackageItem.select().order_by(PackageItem.name)

            with self.assertQueryCount(2):
                query = prefetch(packages, items, prefetch_type=pt)
                for package, (barcode, items) in zip(query, data):
                    self.assertEqual(package.barcode, barcode)
                    self.assertEqual([item.name for item in package.items],
                                     list(items))

    def test_prefetch_mark_dirty_regression(self):
        for pt in PREFETCH_TYPE.values():
            people = Person.select().order_by(Person.name)
            query = people.prefetch(Note, NoteItem, prefetch_type=pt)
            for person in query:
                self.assertEqual(person.dirty_fields, [])
                for note in person.notes:
                    self.assertEqual(note.dirty_fields, [])
                    for item in note.items:
                        self.assertEqual(item.dirty_fields, [])



class X(TestModel):
    name = TextField()
class Z(TestModel):
    x = ForeignKeyField(X)
    name = TextField()

class A(TestModel):
    name = TextField()
    x = ForeignKeyField(X)
class B(TestModel):
    name = TextField()
    a = ForeignKeyField(A)
    x = ForeignKeyField(X)
class C(TestModel):
    name = TextField()
    b = ForeignKeyField(B)
    x = ForeignKeyField(X, null=True)

class C1(TestModel):
    name = TextField()
    c = ForeignKeyField(C)
class C2(TestModel):
    name = TextField()
    c = ForeignKeyField(C)


class TestPrefetchMultiRefs(ModelTestCase):
    database = get_in_memory_db()
    requires = [X, Z, A, B, C, C1, C2]

    def test_prefetch_multirefs(self):
        x1, x2, x3 = [X.create(name=n) for n in ('x1', 'x2', 'x3')]
        for i, x in enumerate((x1, x2, x3), 1):
            for j in range(i):
                Z.create(x=x, name='%s-z%s' % (x.name, j))

        xs = {x.name: x for x in X.select()}
        xs[None] = None

        data = [
            ('a1',
             'x1',
             ['x1-z0'],
             [
                 ('a1-b1', 'x1', ['x1-z0'], [
                     ('a1-b1-c1', 'x1', ['x1-z0'], [], []),
                 ]),
             ]),
            ('a2',
             'x2',
             ['x2-z0', 'x2-z1'],
             [
                 ('a2-b1', 'x1', ['x1-z0'], [
                     ('a2-b1-c1', 'x1', ['x1-z0'], [], []),
                 ]),
                 ('a2-b2', 'x2', ['x2-z0', 'x2-z1'], [
                     ('a2-b2-c1', 'x2', ['x2-z0', 'x2-z1'], [], []),
                     ('a2-b2-c2', 'x1', ['x1-z0'], [], []),
                     ('a2-b2-cx', None, [], [], []),
                 ]),
             ]),
            ('a3',
             'x3',
             ['x3-z0', 'x3-z1', 'x3-z2'],
             [
                 ('a3-b1', 'x1', ['x1-z0'], [
                     ('a3-b1-c1', 'x1', ['x1-z0'], [], []),
                 ]),
                 ('a3-b2', 'x2', ['x2-z0', 'x2-z1'], [
                     ('a3-b2-c1', 'x2', ['x2-z0', 'x2-z1'], [], []),
                     ('a3-b2-c2', 'x2', ['x2-z0', 'x2-z1'], [], []),
                     ('a3-b2-cx1', None, [], [], []),
                     ('a3-b2-cx2', None, [], [], []),
                     ('a3-b2-cx3', None, [], [], []),
                 ]),
                 ('a3-b3', 'x3', ['x3-z0', 'x3-z1', 'x3-z2'], [
                     ('a3-b3-c1', 'x3', ['x3-z0', 'x3-z1', 'x3-z2'], [], []),
                     ('a3-b3-c2', 'x3', ['x3-z0', 'x3-z1', 'x3-z2'], [], []),
                     ('a3-b3-c3', 'x3', ['x3-z0', 'x3-z1', 'x3-z2'],
                      ['c1-1', 'c1-2', 'c1-3', 'c1-4'],
                      ['c2-1', 'c2-2']),
                 ]),
             ]),
        ]

        for a, ax, azs, bs in data:
            a = A.create(name=a, x=xs[ax])
            for b, bx, bzs, cs in bs:
                b = B.create(name=b, a=a, x=xs[bx])
                for c, cx, czs, c1s, c2s in cs:
                    c = C.create(name=c, b=b, x=xs[cx])
                    for c1 in c1s:
                        C1.create(name=c1, c=c)
                    for c2 in c2s:
                        C2.create(name=c2, c=c)


        AX = X.alias('ax')
        AXZ = Z.alias('axz')
        BX = X.alias('bx')
        BXZ = Z.alias('bxz')
        CX = X.alias('cx')
        CXZ = Z.alias('cxz')

        with self.assertQueryCount(11):
            q = prefetch(A.select().order_by(A.name), *(
                (AX, A), (AXZ, AX),
                (B, A), (BX, B), (BXZ, BX),
                (C, B), (CX, C), (CXZ, CX),
                (C1, C), (C2, C)))

        with self.assertQueryCount(0):
            accum = []
            for a in list(q):
                azs = [z.name for z in a.x.z_set]
                bs = []
                for b in a.b_set:
                    bzs = [z.name for z in b.x.z_set]
                    cs = []
                    for c in b.c_set:
                        czs = [z.name for z in c.x.z_set] if c.x else []
                        c1s = [c1.name for c1 in c.c1_set]
                        c2s = [c2.name for c2 in c.c2_set]
                        cs.append((c.name, c.x.name if c.x else None, czs,
                                   c1s, c2s))

                    bs.append((b.name, b.x.name, bzs, cs))
                accum.append((a.name, a.x.name, azs, bs))

        self.assertEqual(data, accum)
