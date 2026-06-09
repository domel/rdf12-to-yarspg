from core.rdf_to_lpg_dani import Variant3


def run():
    rdf_data = """
        PREFIX : <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        :bob :says _:1 .
        :bob :thinks _:1 .
        :bob :likes _:2 .

        _:1 rdf:reifies <<( :moon :made_of :cheese )>> .
        _:1 rdf:reifies <<( :sun :made_of :pop_corn )>> .

        """

    translator = Variant3()
    translator.translate(rdf_data_content=rdf_data,
                         namespaces_dict={"http://example.org/": "",
                                          "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf"})


if __name__ == "__main__":
    run()